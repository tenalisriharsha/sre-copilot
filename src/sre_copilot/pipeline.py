"""In-process alert processing pipeline.

Phase 1: alerts are validated, normalized and queued in memory.
Phase 2: a RAG stage retrieves matching runbook excerpts for each alert.
Phase 3: a metrics stage correlates each alert with recent Prometheus metrics.
Later phases add LLM diagnosis and Slack notification.
"""

import logging

from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.rag.documents import RetrievalHit
from sre_copilot.rag.retriever import RunbookRetriever

logger = logging.getLogger(__name__)


class AlertPipeline:
    """Accepts alert groups and runs them through the processing stages."""

    def __init__(
        self,
        retriever: RunbookRetriever | None = None,
        correlator: MetricsCorrelator | None = None,
    ) -> None:
        self._retriever = retriever
        self._correlator = correlator
        self._queue: list[Alert] = []
        self._retrievals: dict[str, list[RetrievalHit]] = {}
        self._metrics: dict[str, MetricsSnapshot] = {}

    async def process(self, payload: WebhookPayload) -> list[str]:
        """Queue every alert in the group; return their fingerprints."""
        fingerprints: list[str] = []
        for alert in payload.alerts:
            hits = self._retriever.retrieve(alert) if self._retriever else []
            self._retrievals[alert.fingerprint] = hits
            snapshot = await self._correlator.correlate(alert) if self._correlator else None
            if snapshot is not None:
                self._metrics[alert.fingerprint] = snapshot
            logger.info(
                "alert received name=%s severity=%s status=%s fingerprint=%s "
                "runbook_hits=%d metric_series=%d",
                alert.alertname,
                alert.severity,
                alert.status,
                alert.fingerprint,
                len(hits),
                len(snapshot.series) if snapshot else 0,
            )
            self._queue.append(alert)
            fingerprints.append(alert.fingerprint)
        return fingerprints

    def retrieval_for(self, fingerprint: str) -> list[RetrievalHit]:
        """Return the runbook hits recorded for an alert fingerprint."""
        return self._retrievals.get(fingerprint, [])

    def metrics_for(self, fingerprint: str) -> MetricsSnapshot | None:
        """Return the metrics snapshot recorded for an alert fingerprint."""
        return self._metrics.get(fingerprint)

    @property
    def pending(self) -> int:
        return len(self._queue)

    def drain(self) -> list[Alert]:
        """Pop all queued alerts (used by workers and tests)."""
        alerts, self._queue = self._queue, []
        return alerts
