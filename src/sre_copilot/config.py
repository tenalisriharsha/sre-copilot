"""Application settings, loaded from environment variables (12-factor)."""

from functools import lru_cache
from typing import Literal

from pydantic import PositiveFloat, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for sre-copilot.

    Every field maps to an env var prefixed with ``SRE_COPILOT_``
    (e.g. ``SRE_COPILOT_LOG_LEVEL=debug``).
    """

    model_config = SettingsConfigDict(env_prefix="SRE_COPILOT_", extra="ignore")

    app_name: str = "sre-copilot"
    environment: str = "development"
    log_level: str = "info"

    # Slack notification. No webhook URL disables the stage entirely.
    slack_webhook_url: str | None = None
    slack_timeout_seconds: float = 5.0
    # Empty URL disables metrics correlation entirely.
    prometheus_url: str = "http://prometheus:9090"
    prometheus_timeout_seconds: float = 5.0
    chroma_persist_dir: str = ".chroma"
    runbooks_dir: str = "runbooks"
    # LLM diagnosis. No API key disables the diagnosis stage entirely.
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 30.0

    # RAG pipeline.
    # "hash" is a deterministic, dependency-free embedder (default, works
    # offline); "sentence-transformers" loads a real local model.
    embedding_backend: Literal["hash", "sentence-transformers"] = "hash"
    embedding_model: str = "all-MiniLM-L6-v2"
    retrieval_top_k: int = 3

    # Metrics correlation.
    metrics_window_minutes: int = 30
    metrics_step_seconds: int = 60

    # Background processing. The webhook acks after runbook retrieval; the
    # metrics, diagnosis and Slack stages run in background tasks, at most
    # ``pipeline_concurrency`` alerts at a time. Past ``pipeline_max_pending``
    # unfinished alerts the webhook answers 503 so Alertmanager retries later.
    pipeline_concurrency: PositiveInt = 4
    pipeline_max_pending: PositiveInt = 1000
    # Per-alert state (stage results, delivery dedupe) is forgotten after this
    # TTL, and the oldest entries are dropped past the size cap.
    alert_state_ttl_seconds: PositiveFloat = 3600.0
    alert_state_max_entries: PositiveInt = 10_000


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
