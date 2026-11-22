"""Regression tests: app shutdown must close every stage's HTTP client.

Issue #16: PrometheusClient, OpenAICompatibleClient and SlackWebhookClient
each open their own httpx.AsyncClient and expose an aclose() that closes it,
but the app's lifespan shutdown hook only closed the pipeline, leaking the
underlying connection pools for Prometheus, the LLM provider and Slack.
"""

from sre_copilot.config import get_settings
from sre_copilot.main import create_app


async def _run_lifespan(app):
    async with app.router.lifespan_context(app):
        pass


async def test_lifespan_closes_correlator_diagnoser_notifier_clients(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_PROMETHEUS_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("SRE_COPILOT_LLM_API_KEY", "x")
    monkeypatch.setenv("SRE_COPILOT_SLACK_WEBHOOK_URL", "http://127.0.0.1:9998/hook")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.state.correlator is not None
        assert app.state.diagnoser is not None
        assert app.state.notifier is not None

        await _run_lifespan(app)

        assert app.state.correlator._client._client.is_closed is True
        assert app.state.diagnoser._client._client.is_closed is True
        assert app.state.notifier._client._client.is_closed is True
    finally:
        get_settings.cache_clear()


async def test_lifespan_closes_cleanly_with_all_optional_stages_disabled(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_PROMETHEUS_URL", "")
    monkeypatch.setenv("SRE_COPILOT_LLM_API_KEY", "")
    monkeypatch.setenv("SRE_COPILOT_SLACK_WEBHOOK_URL", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.state.correlator is None
        assert app.state.diagnoser is None
        assert app.state.notifier is None

        # Must not raise even though none of the optional stages are wired up.
        await _run_lifespan(app)
    finally:
        get_settings.cache_clear()


async def test_lifespan_closes_cleanly_with_a_subset_of_stages_enabled(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_PROMETHEUS_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("SRE_COPILOT_LLM_API_KEY", "")
    monkeypatch.setenv("SRE_COPILOT_SLACK_WEBHOOK_URL", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.state.correlator is not None
        assert app.state.diagnoser is None
        assert app.state.notifier is None

        await _run_lifespan(app)

        assert app.state.correlator._client._client.is_closed is True
    finally:
        get_settings.cache_clear()
