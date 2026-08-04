"""In-process alert processing pipeline.

Phase 1: alerts are validated, normalized and queued in memory.
Phase 2: a RAG stage retrieves matching runbook excerpts for each alert.
Phase 3: a metrics stage correlates each alert with recent Prometheus metrics.
Phase 4: an LLM stage diagnoses each alert from its runbooks and metrics.
Later phases add Slack notification.
"""

import logging

from sre_copilot.llm.client import LLMError
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.llm.models import Diagnosis
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
        diagnoser: DiagnosisService | None = None,
    ) -> None:
        self._retriever = retriever
        self._correlator = correlator
        self._diagnoser = diagnoser
        self._queue: list[Alert] = []
        self._retrievals: dict[str, list[RetrievalHit]] = {}
        self._metrics: dict[str, MetricsSnapshot] = {}
        self._diagnoses: dict[str, Diagnosis] = {}

    async def process(self, payload: WebhookPayload) -> list[str]:
        """Queue every alert in the group; return their fingerprints."""
        fingerprints: list[str] = []
        for alert in payload.alerts:
            hits = self._retriever.retrieve(alert) if self._retriever else []
            self._retrievals[alert.fingerprint] = hits
            snapshot = await self._correlator.correlate(alert) if self._correlator else None
            if snapshot is not None:
                self._metrics[alert.fingerprint] = snapshot
            diagnosis = await self._diagnose(alert, hits, snapshot)
            if diagnosis is not None:
                self._diagnoses[alert.fingerprint] = diagnosis
            logger.info(
                "alert received name=%s severity=%s status=%s fingerprint=%s "
                "runbook_hits=%d metric_series=%d diagnosed=%s",
                alert.alertname,
                alert.severity,
                alert.status,
                alert.fingerprint,
                len(hits),
                len(snapshot.series) if snapshot else 0,
                diagnosis is not None,
            )
            self._queue.append(alert)
            fingerprints.append(alert.fingerprint)
        return fingerprints

    async def _diagnose(
        self,
        alert: Alert,
        hits: list[RetrievalHit],
        snapshot: MetricsSnapshot | None,
    ) -> Diagnosis | None:
        """Run the diagnosis stage; an LLM failure means "no diagnosis"."""
        if self._diagnoser is None:
            return None
        try:
            return await self._diagnoser.diagnose(alert, hits, snapshot)
        except LLMError as exc:
            logger.warning(
                "diagnosis unavailable alert=%s fingerprint=%s error=%s",
                alert.alertname,
                alert.fingerprint,
                exc,
            )
            return None

    def retrieval_for(self, fingerprint: str) -> list[RetrievalHit]:
        """Return the runbook hits recorded for an alert fingerprint."""
        return self._retrievals.get(fingerprint, [])

    def metrics_for(self, fingerprint: str) -> MetricsSnapshot | None:
        """Return the metrics snapshot recorded for an alert fingerprint."""
        return self._metrics.get(fingerprint)

    def diagnosis_for(self, fingerprint: str) -> Diagnosis | None:
        """Return the diagnosis recorded for an alert fingerprint."""
        return self._diagnoses.get(fingerprint)

    @property
    def pending(self) -> int:
        return len(self._queue)

    def drain(self) -> list[Alert]:
        """Pop all queued alerts (used by workers and tests)."""
        alerts, self._queue = self._queue, []
        return alerts
