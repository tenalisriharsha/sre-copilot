"""Tests for the Block Kit builder, the notifier and pipeline wiring."""

from datetime import UTC, datetime

import pytest

from sre_copilot.config import Settings
from sre_copilot.llm.models import Diagnosis
from sre_copilot.metrics.models import MetricPoint, MetricSeries, MetricsSnapshot
from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.documents import RetrievalHit, RunbookChunk
from sre_copilot.slack.client import SlackError
from sre_copilot.slack.messages import build_message
from sre_copilot.slack.notifier import SlackNotifier


def make_alert(**labels: str) -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": "KubePodCrashLooping", "severity": "critical", **labels},
        annotations={"summary": "pod crash looping"},
        startsAt=datetime(2026, 7, 31, 2, 14, 3, tzinfo=UTC),
        fingerprint="test-fingerprint",
    )


def make_hit() -> RetrievalHit:
    chunk = RunbookChunk(
        id="crashloopbackoff::overview",
        runbook="crashloopbackoff",
        title="CrashLoopBackOff",
        section="overview",
        text="# CrashLoopBackOff\nCheck container logs and recent deploys.",
    )
    return RetrievalHit(chunk=chunk, score=0.87)


def make_snapshot() -> MetricsSnapshot:
    series = MetricSeries(
        name="cpu_cores",
        query="sum(rate(...))",
        points=(MetricPoint(timestamp=1722384000, value=0.5),),
    )
    return MetricsSnapshot(window_minutes=30, series=(series,))


def make_diagnosis() -> Diagnosis:
    return Diagnosis(
        likely_cause="container exits on startup",
        confidence="high",
        remediation_steps=["check logs", "roll back deploy"],
    )


def block_texts(message: dict) -> list[str]:
    """Flatten every text payload in the attachment blocks for assertions."""
    blocks = message["attachments"][0]["blocks"]
    texts = [block["text"]["text"] for block in blocks if "text" in block]
    for block in blocks:
        texts.extend(el["text"] for el in block.get("elements", []))
    return texts


# --- Block Kit builder ------------------------------------------------------


def test_build_message_full_pipeline_output():
    message = build_message(
        make_alert(namespace="payments"), [make_hit()], make_snapshot(), make_diagnosis()
    )

    assert message["text"].startswith("FIRING: KubePodCrashLooping")
    assert message["attachments"][0]["color"] == "danger"
    texts = "\n".join(block_texts(message))
    assert "FIRING: KubePodCrashLooping" in texts
    assert "payments" in texts
    assert "pod crash looping" in texts
    assert "container exits on startup" in texts
    assert "confidence: high" in texts
    assert "1. check logs" in texts
    assert "2. roll back deploy" in texts
    assert "CrashLoopBackOff — overview (score 0.87)" in texts
    assert "Check container logs" in texts
    assert "cpu_cores" in texts
    assert "latest 0.5" in texts


@pytest.mark.parametrize(
    ("severity", "status", "color"),
    [
        ("critical", "firing", "danger"),
        ("warning", "firing", "warning"),
        ("info", "firing", "#439FE0"),
        ("page", "firing", "#439FE0"),
        ("critical", "resolved", "good"),
    ],
)
def test_build_message_colors(severity: str, status: str, color: str):
    alert = make_alert(severity=severity).model_copy(update={"status": status})
    message = build_message(alert)
    assert message["attachments"][0]["color"] == color


def test_build_message_falls_back_without_evidence():
    message = build_message(make_alert())
    texts = "\n".join(block_texts(message))
    assert "No diagnosis available (LLM stage disabled or failed)." in texts
    assert "No matching runbook excerpt found." in texts
    assert "Metrics correlation is disabled." in texts


def test_build_message_reports_metrics_error_and_empty_snapshot():
    errored = MetricsSnapshot(window_minutes=30, error="connection refused")
    texts = "\n".join(block_texts(build_message(make_alert(), snapshot=errored)))
    assert "Metrics unavailable: connection refused" in texts

    empty = MetricsSnapshot(window_minutes=45)
    texts = "\n".join(block_texts(build_message(make_alert(), snapshot=empty)))
    assert "No metric data in the last 45m." in texts


def test_build_message_falls_back_without_summary_annotation():
    alert = make_alert().model_copy(update={"annotations": {}})
    texts = "\n".join(block_texts(build_message(alert)))
    assert "No summary annotation." in texts


def test_build_message_truncates_long_header_and_excerpt():
    alert = make_alert(alertname="X" * 200)
    hit = RetrievalHit(
        chunk=RunbookChunk(
            id="r::s",
            runbook="r",
            title="R",
            section="s",
            text="line\n" * 500,
        ),
        score=0.5,
    )
    message = build_message(alert, [hit])
    blocks = message["attachments"][0]["blocks"]
    header = blocks[0]["text"]["text"]
    assert len(header) <= 150  # Slack header limit, icon included
    runbook_text = next(
        b["text"]["text"] for b in blocks if "text" in b and "*Runbook:*" in b["text"]["text"]
    )
    assert "…" in runbook_text


# --- SlackNotifier ----------------------------------------------------------


class FakeSlackClient:
    """Fake SlackWebhookClient with a canned outcome."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.posts: list[dict] = []

    async def post(self, message: dict) -> None:
        if self._error is not None:
            raise self._error
        self.posts.append(message)


def test_from_settings_returns_none_without_webhook_url():
    assert SlackNotifier.from_settings(Settings(slack_webhook_url=None)) is None


def test_from_settings_builds_notifier_with_webhook_url():
    settings = Settings(
        slack_webhook_url="https://hooks.slack.com/services/T/B/x",
        slack_timeout_seconds=7.0,
    )
    notifier = SlackNotifier.from_settings(settings)
    assert notifier is not None
    client = notifier._client
    assert client._webhook_url == "https://hooks.slack.com/services/T/B/x"
    assert client._client.timeout.read == 7.0


async def test_notify_posts_built_message():
    client = FakeSlackClient()
    notifier = SlackNotifier(client=client)

    await notifier.notify(make_alert(), [make_hit()], make_snapshot(), make_diagnosis())

    assert len(client.posts) == 1
    assert client.posts[0]["attachments"][0]["color"] == "danger"


async def test_notify_propagates_slack_error():
    notifier = SlackNotifier(client=FakeSlackClient(SlackError("boom")))
    with pytest.raises(SlackError, match="boom"):
        await notifier.notify(make_alert(), [], None, None)


# --- Pipeline wiring --------------------------------------------------------


async def test_pipeline_records_delivery_per_fingerprint():
    client = FakeSlackClient()
    pipeline = AlertPipeline(notifier=SlackNotifier(client=client))

    fingerprints = await pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()]))

    assert fingerprints == ["test-fingerprint"]
    assert pipeline.slack_for("test-fingerprint") is True
    assert pipeline.slack_for("unknown") is None
    assert len(client.posts) == 1


async def test_pipeline_degrades_gracefully_when_delivery_fails():
    notifier = SlackNotifier(client=FakeSlackClient(SlackError("boom")))
    pipeline = AlertPipeline(notifier=notifier)

    fingerprints = await pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()]))

    assert fingerprints == ["test-fingerprint"]
    assert pipeline.slack_for("test-fingerprint") is False
    assert pipeline.pending == 1  # the alert is still queued


async def test_pipeline_without_notifier_reports_none():
    pipeline = AlertPipeline()
    await pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()]))
    assert pipeline.slack_for("test-fingerprint") is None


async def test_pipeline_notification_carries_full_context():
    """End to end: diagnosis, runbooks and metrics land in the Slack payload."""
    from sre_copilot.llm.diagnosis import DiagnosisService

    class FakeLLMClient:
        async def complete_json(self, *, system: str, user: str) -> str:
            return (
                '{"likely_cause": "bad deploy", "confidence": "medium", '
                '"remediation_steps": ["roll back"]}'
            )

    client = FakeSlackClient()
    pipeline = AlertPipeline(
        diagnoser=DiagnosisService(client=FakeLLMClient()),
        notifier=SlackNotifier(client=client),
    )
    await pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()]))

    assert len(client.posts) == 1
    texts = "\n".join(block_texts(client.posts[0]))
    assert "bad deploy" in texts
    assert "1. roll back" in texts
