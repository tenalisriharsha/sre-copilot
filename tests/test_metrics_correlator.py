"""Tests for the metrics correlation service (mocked Prometheus transport)."""

from datetime import UTC, datetime

import httpx
import pytest

from sre_copilot.config import Settings
from sre_copilot.metrics.client import PrometheusClient
from sre_copilot.metrics.correlator import QUERIES, MetricsCorrelator
from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.pipeline import AlertPipeline


def make_alert(**labels: str) -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": "KubePodCrashLooping", "severity": "critical", **labels},
        annotations={"summary": "pod crash looping"},
        startsAt=datetime(2026, 7, 31, 2, 14, 3, tzinfo=UTC),
        fingerprint="test-fingerprint",
    )


def matrix(values: list[list]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {}, "values": values}],
        },
    }


def make_correlator(handler, **kwargs) -> MetricsCorrelator:
    client = PrometheusClient(
        "http://prometheus:9090",
        transport=httpx.MockTransport(handler),
    )
    return MetricsCorrelator(client=client, **kwargs)


async def test_correlate_fetches_all_metric_families():
    queries_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["query"])
        return httpx.Response(200, json=matrix([[1722384000, "0.5"], [1722384060, "0.7"]]))

    correlator = make_correlator(handler)
    alert = make_alert(namespace="payments", pod="payments-api-x2v4k")
    snapshot = await correlator.correlate(alert)

    assert snapshot.error is None
    assert snapshot.window_minutes == 30
    assert [series.name for series in snapshot.series] == list(QUERIES)
    assert len(queries_seen) == len(QUERIES)
    cpu = snapshot.series[0]
    assert cpu.latest_value == 0.7
    assert len(cpu.points) == 2


async def test_correlate_builds_selector_from_alert_labels():
    queries_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["query"])
        return httpx.Response(200, json=matrix([]))

    correlator = make_correlator(handler)
    alert = make_alert(namespace="payments", pod="payments-api-x2v4k", container="api")
    await correlator.correlate(alert)

    for query in queries_seen:
        assert 'namespace="payments"' in query
        assert 'pod="payments-api-x2v4k"' in query
        assert 'container="api"' in query
        # Non-identifying labels never leak into the selector.
        assert "alertname" not in query
        assert "severity" not in query


async def test_correlate_without_labels_skips_prometheus():
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Prometheus must not be queried for alerts without labels")

    correlator = make_correlator(handler)
    snapshot = await correlator.correlate(make_alert())
    assert snapshot.series == ()
    assert snapshot.error is None


async def test_correlate_degrades_gracefully_when_prometheus_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    correlator = make_correlator(handler)
    alert = make_alert(namespace="payments", pod="payments-api-x2v4k")
    snapshot = await correlator.correlate(alert)

    assert snapshot.series == ()
    assert snapshot.error is not None
    assert "name resolution failed" in snapshot.error


async def test_correlate_degrades_gracefully_on_error_payload():
    client_response = httpx.Response(400, json={"status": "error", "error": "parse error"})
    correlator = make_correlator(lambda request: client_response)
    snapshot = await correlator.correlate(make_alert(namespace="payments"))
    assert snapshot.series == ()
    assert snapshot.error is not None


def test_from_settings_returns_none_without_url():
    settings = Settings(prometheus_url="")
    assert MetricsCorrelator.from_settings(settings) is None


def test_from_settings_builds_correlator_with_url():
    settings = Settings(
        prometheus_url="http://prometheus:9090",
        metrics_window_minutes=15,
        metrics_step_seconds=30,
    )
    correlator = MetricsCorrelator.from_settings(settings)
    assert correlator is not None
    assert correlator._window_minutes == 15
    assert correlator._step_seconds == 30


async def test_pipeline_records_snapshot_per_fingerprint():
    correlator = make_correlator(
        lambda request: httpx.Response(200, json=matrix([[1722384000, "1"]]))
    )
    alert = make_alert(namespace="payments", pod="payments-api-x2v4k")
    payload = WebhookPayload(status="firing", alerts=[alert])
    pipeline = AlertPipeline(correlator=correlator)

    fingerprints = await pipeline.process(payload)

    assert fingerprints == ["test-fingerprint"]
    snapshot = pipeline.metrics_for("test-fingerprint")
    assert snapshot is not None
    assert len(snapshot.series) == len(QUERIES)
    assert pipeline.metrics_for("unknown") is None


async def test_correlate_degrades_on_malformed_prometheus_response():
    """A non-Prometheus 200 must yield an error snapshot, not raise."""
    correlator = make_correlator(lambda request: httpx.Response(200, text="<html>proxy</html>"))
    snapshot = await correlator.correlate(make_alert(namespace="payments"))
    assert snapshot.series == ()
    assert snapshot.error is not None
