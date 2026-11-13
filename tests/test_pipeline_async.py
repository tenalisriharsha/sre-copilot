"""Background processing: prompt acks, retry dedupe, bounded concurrency and state."""

import asyncio
import copy
import logging
import time

import pytest

from sre_copilot.config import Settings
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.models import WebhookPayload
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.slack.notifier import SlackNotifier

DIAGNOSIS_JSON = (
    '{"likely_cause": "bad deploy", "confidence": "medium", "remediation_steps": ["roll back"]}'
)
FINGERPRINTS = ["a1b2c3d4e5f60718", "f60718a1b2c3d4e5"]


class SlowLLMClient:
    """An LLM that takes ``delay`` seconds per call and tracks its concurrency."""

    def __init__(self, delay: float = 0.0, gate: asyncio.Event | None = None) -> None:
        self.delay = delay
        self.gate = gate
        self.calls = 0
        self.active = 0
        self.peak = 0

    async def complete_json(self, *, system: str, user: str) -> str:
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        return DIAGNOSIS_JSON


class RecordingSlackClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, message: dict) -> None:
        self.posts.append(message)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_payload(count: int, status: str = "firing") -> dict:
    return {
        "status": status,
        "receiver": "sre-copilot",
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": "KubePodCrashLooping", "pod": f"api-{i}"},
                "startsAt": "2026-07-31T02:14:03Z",
                "fingerprint": f"fp-{i:04d}",
            }
            for i in range(count)
        ],
    }


async def test_webhook_acks_promptly_while_llm_is_slow(app, client, alertmanager_payload):
    """A 2 s LLM call per alert must not hold the webhook response."""
    llm = SlowLLMClient(delay=2.0)
    slack = RecordingSlackClient()
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        diagnoser=DiagnosisService(client=llm),
        notifier=SlackNotifier(client=slack),
    )

    started = time.perf_counter()
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    elapsed = time.perf_counter() - started

    assert resp.status_code == 202
    assert elapsed < 0.5, f"webhook took {elapsed:.2f}s with a 2s LLM"
    detail = resp.json()["detail"]
    # Fast local work is still in the ack...
    assert detail["runbooks"][FINGERPRINTS[0]][0]["runbook"] == "crashloopbackoff"
    assert detail["processing"] == {fp: "scheduled" for fp in FINGERPRINTS}
    # ...while the slow stages have not finished yet.
    assert detail["diagnosis"] == {fp: None for fp in FINGERPRINTS}
    assert slack.posts == []
    status = await client.get(f"/api/v1/alerts/{FINGERPRINTS[0]}")
    assert status.json()["state"] == "processing"

    await app.state.pipeline.join()

    assert len(slack.posts) == 2
    status = await client.get(f"/api/v1/alerts/{FINGERPRINTS[0]}")
    body = status.json()
    assert body["state"] == "done"
    assert body["diagnosis"]["likely_cause"] == "bad deploy"
    assert body["slack"] == {"delivered": True}
    assert body["runbooks"][0]["runbook"] == "crashloopbackoff"


async def test_alertmanager_retry_does_not_post_twice(app, client, alertmanager_payload):
    """Alertmanager re-sends the same group on timeout; Slack must get one post per alert."""
    gate = asyncio.Event()
    slack = RecordingSlackClient()
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        diagnoser=DiagnosisService(client=SlowLLMClient(gate=gate)),
        notifier=SlackNotifier(client=slack),
    )

    # wait_for: with an inline pipeline the gated LLM would block these forever.
    first = await asyncio.wait_for(client.post("/api/v1/alerts", json=alertmanager_payload), 5)
    # Retry while the first delivery is still being processed...
    retry = await asyncio.wait_for(client.post("/api/v1/alerts", json=alertmanager_payload), 5)
    gate.set()
    await app.state.pipeline.join()
    # ...and once more after it finished.
    late_retry = await client.post("/api/v1/alerts", json=alertmanager_payload)
    await app.state.pipeline.join()

    assert first.json()["detail"]["processing"] == {fp: "scheduled" for fp in FINGERPRINTS}
    for resp in (retry, late_retry):
        assert resp.status_code == 202
        assert resp.json()["fingerprints"] == FINGERPRINTS
        assert resp.json()["detail"]["processing"] == {fp: "duplicate" for fp in FINGERPRINTS}
        assert resp.json()["detail"]["runbooks"][FINGERPRINTS[0]]
    # The late retry's ack already carries the finished results.
    assert late_retry.json()["detail"]["slack"][FINGERPRINTS[0]] == {"delivered": True}
    assert len(slack.posts) == 2


async def test_resolved_alert_is_posted_after_firing(app, client, alertmanager_payload):
    """Dedupe is per (fingerprint, status, startsAt): resolution is a new event."""
    slack = RecordingSlackClient()
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever, notifier=SlackNotifier(client=slack)
    )
    resolved = copy.deepcopy(alertmanager_payload)
    resolved["status"] = "resolved"
    for alert in resolved["alerts"]:
        alert["status"] = "resolved"

    await client.post("/api/v1/alerts", json=alertmanager_payload)
    await client.post("/api/v1/alerts", json=resolved)
    await app.state.pipeline.join()

    assert len(slack.posts) == 4
    assert [post["attachments"][0]["color"] for post in slack.posts[2:]] == ["good", "good"]


async def test_alerts_without_fingerprint_are_not_deduplicated():
    """Without a fingerprint two different alerts can't be told apart; process both."""
    slack = RecordingSlackClient()
    pipeline = AlertPipeline(notifier=SlackNotifier(client=slack))
    payload = make_payload(1)
    payload["alerts"][0]["fingerprint"] = ""

    await pipeline.process(WebhookPayload.model_validate(payload))
    await pipeline.process(WebhookPayload.model_validate(payload))

    assert len(slack.posts) == 2


async def test_background_stages_respect_concurrency_limit():
    llm = SlowLLMClient(delay=0.05)
    pipeline = AlertPipeline(diagnoser=DiagnosisService(client=llm), concurrency=2)

    submissions = pipeline.submit(WebhookPayload.model_validate(make_payload(8)))
    assert pipeline.in_flight == 8
    await pipeline.join()

    assert [s.outcome for s in submissions] == ["scheduled"] * 8
    assert llm.calls == 8
    assert llm.peak == 2
    assert pipeline.in_flight == 0


async def test_webhook_returns_503_when_at_capacity_and_retry_completes(app, client):
    """Past max_pending the webhook asks Alertmanager to retry; the retry skips done alerts."""
    gate = asyncio.Event()
    slack = RecordingSlackClient()
    app.state.pipeline = AlertPipeline(
        diagnoser=DiagnosisService(client=SlowLLMClient(gate=gate)),
        notifier=SlackNotifier(client=slack),
        max_pending=2,
    )
    payload = make_payload(3)

    resp = await client.post("/api/v1/alerts", json=payload)
    assert resp.status_code == 503
    assert resp.json()["detail"]["deferred"] == ["fp-0002"]

    gate.set()
    await app.state.pipeline.join()
    retry = await client.post("/api/v1/alerts", json=payload)
    await app.state.pipeline.join()

    assert retry.status_code == 202
    assert retry.json()["detail"]["processing"] == {
        "fp-0000": "duplicate",
        "fp-0001": "duplicate",
        "fp-0002": "scheduled",
    }
    assert len(slack.posts) == 3


async def test_per_alert_state_expires_after_ttl(app, client):
    clock = FakeClock()
    slack = RecordingSlackClient()
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        notifier=SlackNotifier(client=slack),
        state_ttl_seconds=60,
        clock=clock,
    )
    pipeline = app.state.pipeline
    payload = make_payload(1)

    await client.post("/api/v1/alerts", json=payload)
    await pipeline.join()
    assert pipeline.retrieval_for("fp-0000")
    assert (await client.get("/api/v1/alerts/fp-0000")).status_code == 200

    clock.now += 61

    assert pipeline.record_for("fp-0000") is None
    assert pipeline.retrieval_for("fp-0000") == []
    assert pipeline.slack_for("fp-0000") is None
    assert (await client.get("/api/v1/alerts/fp-0000")).status_code == 404
    # The dedupe entry expired too, so a much later re-delivery
    # (e.g. Alertmanager's repeat_interval) is processed again.
    resp = await client.post("/api/v1/alerts", json=payload)
    await pipeline.join()
    assert resp.json()["detail"]["processing"] == {"fp-0000": "scheduled"}
    assert len(slack.posts) == 2


async def test_per_alert_state_is_capped_at_max_entries():
    pipeline = AlertPipeline(state_max_entries=10)

    for start in range(0, 500, 50):
        payload = make_payload(50)
        for i, alert in enumerate(payload["alerts"]):
            alert["fingerprint"] = f"fp-{start + i:04d}"
        await pipeline.process(WebhookPayload.model_validate(payload))

    assert len(pipeline._records) == 10
    assert len(pipeline._accepted) == 10
    assert pipeline.pending == 10
    assert pipeline.record_for("fp-0000") is None
    assert pipeline.record_for("fp-0499") is not None


async def test_unexpected_stage_error_is_logged_and_contained(caplog):
    class ExplodingSlackClient:
        async def post(self, message: dict) -> None:
            raise RuntimeError("boom")

    pipeline = AlertPipeline(notifier=SlackNotifier(client=ExplodingSlackClient()))

    with caplog.at_level(logging.ERROR, logger="sre_copilot.pipeline"):
        await pipeline.process(WebhookPayload.model_validate(make_payload(1)))

    assert "alert processing failed" in caplog.text
    record = pipeline.record_for("fp-0000")
    assert record is not None and record.done
    assert pipeline.in_flight == 0


async def test_aclose_cancels_alerts_that_outlive_the_timeout():
    llm = SlowLLMClient(gate=asyncio.Event())  # never released
    pipeline = AlertPipeline(diagnoser=DiagnosisService(client=llm))
    pipeline.submit(WebhookPayload.model_validate(make_payload(2)))
    await asyncio.sleep(0)

    await pipeline.aclose(timeout=0.05)

    assert pipeline.in_flight == 0
    assert pipeline.record_for("fp-0000").done


async def test_get_unknown_fingerprint_returns_404(client):
    resp = await client.get("/api/v1/alerts/does-not-exist")
    assert resp.status_code == 404


def test_pipeline_settings_defaults_and_env(monkeypatch):
    settings = Settings()
    assert settings.pipeline_concurrency == 4
    assert settings.pipeline_max_pending == 1000
    assert settings.alert_state_ttl_seconds == 3600
    assert settings.alert_state_max_entries == 10_000

    monkeypatch.setenv("SRE_COPILOT_PIPELINE_CONCURRENCY", "8")
    monkeypatch.setenv("SRE_COPILOT_ALERT_STATE_TTL_SECONDS", "120")
    settings = Settings()
    assert settings.pipeline_concurrency == 8
    assert settings.alert_state_ttl_seconds == 120


def test_pipeline_settings_reject_zero(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_PIPELINE_CONCURRENCY", "0")
    with pytest.raises(ValueError):
        Settings()


def test_app_wires_pipeline_limits_from_settings(monkeypatch):
    from sre_copilot.config import get_settings
    from sre_copilot.main import create_app

    monkeypatch.setenv("SRE_COPILOT_PIPELINE_MAX_PENDING", "7")
    monkeypatch.setenv("SRE_COPILOT_ALERT_STATE_MAX_ENTRIES", "5")
    get_settings.cache_clear()
    try:
        pipeline = create_app().state.pipeline
    finally:
        get_settings.cache_clear()
    assert pipeline._max_pending == 7
    assert pipeline._queue.maxlen == 5
