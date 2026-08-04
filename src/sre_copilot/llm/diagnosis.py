"""Diagnosis service: alert + runbooks + metrics → structured Diagnosis."""

import logging
from collections.abc import Sequence

from pydantic import ValidationError

from sre_copilot.config import Settings
from sre_copilot.llm.client import LLMClient, LLMError, OpenAICompatibleClient
from sre_copilot.llm.models import Diagnosis
from sre_copilot.llm.prompts import build_messages
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert
from sre_copilot.rag.documents import RetrievalHit

logger = logging.getLogger(__name__)


class DiagnosisService:
    """Runs the LLM diagnosis stage for one alert at a time."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "DiagnosisService | None":
        """Build a service from settings, or None when no API key is set."""
        if not settings.llm_api_key:
            return None
        client = OpenAICompatibleClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
        return cls(client=client)

    async def diagnose(
        self,
        alert: Alert,
        runbook_hits: Sequence[RetrievalHit],
        snapshot: MetricsSnapshot | None,
    ) -> Diagnosis:
        """Return a structured diagnosis for the alert.

        Raises ``LLMError`` when the LLM call fails or its response is not a
        valid ``Diagnosis`` — callers treat that as "no diagnosis" rather
        than a pipeline failure.
        """
        system, user = build_messages(alert, runbook_hits, snapshot)
        try:
            raw = await self._client.complete_json(system=system, user=user)
            diagnosis = Diagnosis.model_validate_json(raw)
        except (LLMError, ValidationError) as exc:
            raise LLMError(f"diagnosis failed for alert={alert.alertname}: {exc}") from exc
        logger.info(
            "diagnosed alert=%s fingerprint=%s confidence=%s steps=%d",
            alert.alertname,
            alert.fingerprint,
            diagnosis.confidence,
            len(diagnosis.remediation_steps),
        )
        return diagnosis
