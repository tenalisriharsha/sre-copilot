"""In-process alert processing pipeline.

Phase 1 keeps this intentionally small: alerts are validated, normalized and
queued in memory. Later phases add runbook retrieval (RAG), metrics
correlation, LLM diagnosis and Slack notification as pipeline stages.
"""

import logging

from sre_copilot.models import Alert, WebhookPayload

logger = logging.getLogger(__name__)


class AlertPipeline:
    """Accepts alert groups and runs them through the processing stages."""

    def __init__(self) -> None:
        self._queue: list[Alert] = []

    async def process(self, payload: WebhookPayload) -> list[str]:
        """Queue every alert in the group; return their fingerprints."""
        fingerprints: list[str] = []
        for alert in payload.alerts:
            logger.info(
                "alert received name=%s severity=%s status=%s fingerprint=%s",
                alert.alertname,
                alert.severity,
                alert.status,
                alert.fingerprint,
            )
            self._queue.append(alert)
            fingerprints.append(alert.fingerprint)
        return fingerprints

    @property
    def pending(self) -> int:
        return len(self._queue)

    def drain(self) -> list[Alert]:
        """Pop all queued alerts (used by workers and tests)."""
        alerts, self._queue = self._queue, []
        return alerts
