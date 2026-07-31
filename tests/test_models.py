from datetime import UTC, datetime

from sre_copilot.models import Alert, WebhookPayload


def test_alert_parses_camelcase_fields():
    alert = Alert(
        status="firing",
        labels={"alertname": "HighMemoryUsage", "severity": "warning"},
        annotations={},
        startsAt="2026-07-31T01:00:00Z",
        endsAt="2026-07-31T02:00:00Z",
        generatorURL="http://prometheus:9090/graph",
        fingerprint="abc123",
    )
    assert alert.starts_at == datetime(2026, 7, 31, 1, 0, tzinfo=UTC)
    assert alert.ends_at == datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    assert alert.generator_url == "http://prometheus:9090/graph"
    assert alert.alertname == "HighMemoryUsage"
    assert alert.severity == "warning"


def test_alert_defaults_for_missing_labels():
    alert = Alert(status="resolved", startsAt="2026-07-31T01:00:00Z")
    assert alert.alertname == "unknown"
    assert alert.severity == "unknown"
    assert alert.labels == {}


def test_webhook_payload_parses_group_fields(alertmanager_payload):
    payload = WebhookPayload.model_validate(alertmanager_payload)
    assert payload.version == "4"
    assert payload.status == "firing"
    assert payload.receiver == "sre-copilot"
    assert payload.group_labels["namespace"] == "payments"
    assert payload.common_labels["severity"] == "critical"
    assert len(payload.alerts) == 2
    assert payload.alerts[1].fingerprint == "f60718a1b2c3d4e5"


def test_webhook_payload_rejects_unknown_status():
    payload = {
        "status": "silenced",
        "alerts": [{"status": "firing", "startsAt": "2026-07-31T01:00:00Z"}],
    }
    try:
        WebhookPayload.model_validate(payload)
    except Exception:
        return
    raise AssertionError("expected validation error for status 'silenced'")
