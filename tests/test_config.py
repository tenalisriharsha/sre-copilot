from sre_copilot.config import Settings


def test_settings_defaults():
    settings = Settings()
    assert settings.app_name == "sre-copilot"
    assert settings.environment == "development"
    assert settings.log_level == "info"
    assert settings.prometheus_url == "http://prometheus:9090"
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
