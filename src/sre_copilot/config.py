"""Application settings, loaded from environment variables (12-factor)."""

from functools import lru_cache
from typing import Literal

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

    # Downstream integrations (wired in later phases).
    slack_webhook_url: str | None = None
    prometheus_url: str = "http://prometheus:9090"
    chroma_persist_dir: str = ".chroma"
    runbooks_dir: str = "runbooks"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None

    # RAG pipeline.
    # "hash" is a deterministic, dependency-free embedder (default, works
    # offline); "sentence-transformers" loads a real local model.
    embedding_backend: Literal["hash", "sentence-transformers"] = "hash"
    embedding_model: str = "all-MiniLM-L6-v2"
    retrieval_top_k: int = 3


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
