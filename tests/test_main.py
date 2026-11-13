import httpx
import pytest
from fastapi import FastAPI

from sre_copilot.llm.client import OpenAICompatibleClient
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.main import create_app
from sre_copilot.metrics.client import PrometheusClient
from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.slack.client import SlackWebhookClient
from sre_copilot.slack.notifier import SlackNotifier


def _make_app(
    monkeypatch: pytest.MonkeyPatch, enabled: tuple[str, ...]
) -> tuple[FastAPI, dict[str, httpx.AsyncClient]]:
    clients: dict[str, httpx.AsyncClient] = {}

    def transport() -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: httpx.Response(200))

    correlator = None
    if "correlator" in enabled:
        client = PrometheusClient("http://prometheus", transport=transport())
        clients["correlator"] = client._client
        correlator = MetricsCorrelator(client)
    monkeypatch.setattr(
        MetricsCorrelator,
        "from_settings",
        classmethod(lambda cls, settings: correlator),
    )

    diagnoser = None
    if "diagnoser" in enabled:
        client = OpenAICompatibleClient(
            "http://llm",
            api_key="test",
            model="test",
            transport=transport(),
        )
        clients["diagnoser"] = client._client
        diagnoser = DiagnosisService(client)
    monkeypatch.setattr(
        DiagnosisService,
        "from_settings",
        classmethod(lambda cls, settings: diagnoser),
    )

    notifier = None
    if "notifier" in enabled:
        client = SlackWebhookClient("http://slack/hook", transport=transport())
        clients["notifier"] = client._client
        notifier = SlackNotifier(client)
    monkeypatch.setattr(
        SlackNotifier,
        "from_settings",
        classmethod(lambda cls, settings: notifier),
    )

    return create_app(), clients


@pytest.mark.parametrize(
    "enabled",
    [
        pytest.param((), id="none"),
        pytest.param(("correlator",), id="correlator"),
        pytest.param(("diagnoser",), id="diagnoser"),
        pytest.param(("notifier",), id="notifier"),
        pytest.param(("correlator", "diagnoser"), id="correlator-diagnoser"),
        pytest.param(("correlator", "notifier"), id="correlator-notifier"),
        pytest.param(("diagnoser", "notifier"), id="diagnoser-notifier"),
        pytest.param(("correlator", "diagnoser", "notifier"), id="all"),
    ],
)
async def test_lifespan_closes_configured_clients(monkeypatch, enabled):
    app, clients = _make_app(monkeypatch, enabled)

    async with app.router.lifespan_context(app):
        assert all(not client.is_closed for client in clients.values())

    assert all(client.is_closed for client in clients.values())


async def test_lifespan_closes_clients_when_application_body_raises(monkeypatch):
    app, clients = _make_app(monkeypatch, ("correlator", "diagnoser", "notifier"))

    with pytest.raises(RuntimeError, match="application failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("application failed")

    assert all(client.is_closed for client in clients.values())


async def test_lifespan_closes_clients_when_pipeline_shutdown_raises(monkeypatch):
    app, clients = _make_app(monkeypatch, ("correlator", "diagnoser", "notifier"))

    async def fail_shutdown() -> None:
        raise RuntimeError("pipeline shutdown failed")

    monkeypatch.setattr(app.state.pipeline, "aclose", fail_shutdown)

    with pytest.raises(RuntimeError, match="pipeline shutdown failed"):
        async with app.router.lifespan_context(app):
            pass

    assert all(client.is_closed for client in clients.values())
