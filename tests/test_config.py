from sre_copilot.config import Settings


def test_settings_defaults(monkeypatch):
    # The session conftest blanks these for isolation; remove to test defaults.
    monkeypatch.delenv("SRE_COPILOT_PROMETHEUS_URL", raising=False)
    monkeypatch.delenv("SRE_COPILOT_CHROMA_PERSIST_DIR", raising=False)
    monkeypatch.delenv("SRE_COPILOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SRE_COPILOT_SLACK_WEBHOOK_URL", raising=False)
    settings = Settings()
    assert settings.app_name == "sre-copilot"
    assert settings.environment == "development"
    assert settings.log_level == "info"
    assert settings.prometheus_url == "http://prometheus:9090"
    assert settings.prometheus_timeout_seconds == 5.0
    assert settings.metrics_window_minutes == 30
    assert settings.metrics_step_seconds == 60
    assert settings.slack_webhook_url is None


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_LOG_LEVEL", "debug")
    monkeypatch.setenv("SRE_COPILOT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/x")
    settings = Settings()
    assert settings.log_level == "debug"
    assert settings.slack_webhook_url == "https://hooks.slack.com/services/T/B/x"


def test_settings_ignores_unrelated_env(monkeypatch):
    monkeypatch.setenv("SRE_COPILOT_TOTALLY_UNKNOWN", "nope")
    settings = Settings()
    assert not hasattr(settings, "totally_unknown")
