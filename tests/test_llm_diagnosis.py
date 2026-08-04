"""Tests for the prompt builder and the diagnosis service (fake LLM client)."""

from datetime import UTC, datetime

import pytest

from sre_copilot.config import Settings
from sre_copilot.llm.client import LLMError
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.llm.models import Diagnosis
from sre_copilot.llm.prompts import SYSTEM_PROMPT, build_messages
from sre_copilot.metrics.models import MetricPoint, MetricSeries, MetricsSnapshot
from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.documents import RetrievalHit, RunbookChunk


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


class FakeLLMClient:
    """Fake implementing the LLMClient protocol with a canned response."""

    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


VALID_DIAGNOSIS_JSON = (
    '{"likely_cause": "container exits on startup", "confidence": "high", '
    '"remediation_steps": ["check logs", "roll back deploy"]}'
)


# --- Prompt builder ---------------------------------------------------------


def test_build_messages_includes_alert_runbooks_and_metrics():
    system, user = build_messages(make_alert(namespace="payments"), [make_hit()], make_snapshot())

    assert "JSON" in system
    assert "KubePodCrashLooping" in user
    assert "payments" in user
    assert "CrashLoopBackOff" in user
    assert "Check container logs" in user
    assert "cpu_cores" in user
    assert "0.5" in user


def test_build_messages_degrades_without_evidence():
    _, user = build_messages(make_alert(), [], None)
    assert "No matching runbook excerpts" in user
    assert "Metrics correlation is disabled" in user


def test_build_messages_reports_metrics_error():
    snapshot = MetricsSnapshot(window_minutes=30, error="connection refused")
    _, user = build_messages(make_alert(), [], snapshot)
    assert "Metrics unavailable: connection refused" in user


def test_system_prompt_defines_output_schema():
    for field in Diagnosis.model_fields:
        assert field in SYSTEM_PROMPT


# --- DiagnosisService -------------------------------------------------------


async def test_diagnose_parses_valid_response():
    client = FakeLLMClient(VALID_DIAGNOSIS_JSON)
    service = DiagnosisService(client=client)

    diagnosis = await service.diagnose(make_alert(), [make_hit()], make_snapshot())

    assert diagnosis.likely_cause == "container exits on startup"
    assert diagnosis.confidence == "high"
    assert diagnosis.remediation_steps == ["check logs", "roll back deploy"]
    # The service sent exactly one system + user message pair.
    assert len(client.calls) == 1
    system, user = client.calls[0]
    assert system == SYSTEM_PROMPT
    assert "KubePodCrashLooping" in user


async def test_diagnose_raises_on_client_failure():
    service = DiagnosisService(client=FakeLLMClient(LLMError("LLM request failed: 500")))
    with pytest.raises(LLMError, match="diagnosis failed"):
        await service.diagnose(make_alert(), [], None)


async def test_diagnose_raises_on_invalid_json():
    service = DiagnosisService(client=FakeLLMClient("not json at all"))
    with pytest.raises(LLMError, match="diagnosis failed"):
        await service.diagnose(make_alert(), [], None)


async def test_diagnose_raises_on_schema_violation():
    bad = '{"likely_cause": "x", "confidence": "certain", "remediation_steps": []}'
    service = DiagnosisService(client=FakeLLMClient(bad))
    with pytest.raises(LLMError, match="diagnosis failed"):
        await service.diagnose(make_alert(), [], None)


def test_from_settings_returns_none_without_api_key():
    assert DiagnosisService.from_settings(Settings(llm_api_key=None)) is None


def test_from_settings_builds_service_with_api_key():
    settings = Settings(
        llm_api_key="sk-test",
        llm_model="gpt-test",
        llm_base_url="http://llm.internal/v1",
        llm_timeout_seconds=10.0,
    )
    service = DiagnosisService.from_settings(settings)
    assert service is not None
    client = service._client
    assert client._model == "gpt-test"
    assert str(client._client.base_url) == "http://llm.internal/v1/"
    assert client._client.timeout.read == 10.0


# --- Pipeline wiring --------------------------------------------------------


async def test_pipeline_records_diagnosis_per_fingerprint():
    service = DiagnosisService(client=FakeLLMClient(VALID_DIAGNOSIS_JSON))
    alert = make_alert(namespace="payments")
    pipeline = AlertPipeline(diagnoser=service)

    fingerprints = await pipeline.process(WebhookPayload(status="firing", alerts=[alert]))

    assert fingerprints == ["test-fingerprint"]
    diagnosis = pipeline.diagnosis_for("test-fingerprint")
    assert diagnosis is not None
    assert diagnosis.confidence == "high"
    assert pipeline.diagnosis_for("unknown") is None


async def test_pipeline_degrades_gracefully_when_diagnosis_fails():
    service = DiagnosisService(client=FakeLLMClient(LLMError("boom")))
    pipeline = AlertPipeline(diagnoser=service)

    fingerprints = await pipeline.process(WebhookPayload(status="firing", alerts=[make_alert()]))

    assert fingerprints == ["test-fingerprint"]
    assert pipeline.diagnosis_for("test-fingerprint") is None
    assert pipeline.pending == 1  # the alert is still queued
