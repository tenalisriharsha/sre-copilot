"""In-process alert processing pipeline.

Phase 1: alerts are validated, normalized and queued in memory.
Phase 2: a RAG stage retrieves matching runbook excerpts for each alert.
Phase 3: a metrics stage correlates each alert with recent Prometheus metrics.
Phase 4: an LLM stage diagnoses each alert from its runbooks and metrics.
Phase 5: a Slack stage posts the assembled notification per alert.

Runbook retrieval is local and fast, so it runs while the webhook request is
open and its hits go into the ack. The slow network stages (metrics, LLM,
Slack) run in background tasks, at most ``concurrency`` alerts at a time, so
the webhook acks promptly and Alertmanager never times out and retries.

An alert is processed once per (fingerprint, status, startsAt): a retried or
repeated delivery of the same alert inside the state TTL is acknowledged but
not processed again, so it cannot post a second Slack message. A transition
(firing -> resolved) or a new occurrence (new startsAt) is processed.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sre_copilot.llm.client import LLMError
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.llm.models import Diagnosis
from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert, WebhookPayload
from sre_copilot.rag.documents import RetrievalHit
from sre_copilot.rag.retriever import RunbookRetriever
from sre_copilot.slack.client import SlackError
from sre_copilot.slack.notifier import SlackNotifier
from sre_copilot.state import BoundedTTLMap

logger = logging.getLogger(__name__)

# scheduled: background stages started for this alert.
# duplicate: this exact alert was already accepted within the state TTL.
# deferred: too many alerts in flight; the caller should ask for a retry.
Outcome = Literal["scheduled", "duplicate", "deferred"]


@dataclass
class AlertRecord:
    """Everything the pipeline knows about the latest run for a fingerprint."""

    alert: Alert
    hits: list[RetrievalHit]
    done: bool = False
    metrics: MetricsSnapshot | None = None
    diagnosis: Diagnosis | None = None
    delivered: bool | None = None


@dataclass
class Submission:
    """The result of submitting one alert: its retrieval hits and outcome."""

    fingerprint: str
    outcome: Outcome
    hits: list[RetrievalHit]
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class AlertPipeline:
    """Accepts alert groups and runs them through the processing stages."""

    def __init__(
        self,
        retriever: RunbookRetriever | None = None,
        correlator: MetricsCorrelator | None = None,
        diagnoser: DiagnosisService | None = None,
        notifier: SlackNotifier | None = None,
        *,
        concurrency: int = 4,
        max_pending: int = 1000,
        state_ttl_seconds: float = 3600.0,
        state_max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if concurrency <= 0 or max_pending <= 0:
            raise ValueError("concurrency and max_pending must be positive")
        self._retriever = retriever
        self._correlator = correlator
        self._diagnoser = diagnoser
        self._notifier = notifier
        self._max_pending = max_pending
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        # Accepted alerts awaiting a consumer; bounded so nothing grows forever.
        self._queue: deque[Alert] = deque(maxlen=state_max_entries)
        self._records: BoundedTTLMap[str, AlertRecord] = BoundedTTLMap(
            state_max_entries, state_ttl_seconds, clock
        )
        self._accepted: BoundedTTLMap[tuple[str, str, datetime], None] = BoundedTTLMap(
            state_max_entries, state_ttl_seconds, clock
        )

    def submit(self, payload: WebhookPayload) -> list[Submission]:
        """Retrieve runbooks inline and start the slow stages in the background.

        Must be called from a running event loop. Returns immediately; the
        background work is tracked and can be awaited with ``join()``.
        """
        submissions: list[Submission] = []
        for alert in payload.alerts:
            hits = self._retriever.retrieve(alert) if self._retriever else []
            key = _delivery_key(alert)
            task: asyncio.Task[None] | None = None
            if key is not None and key in self._accepted:
                outcome: Outcome = "duplicate"
            elif len(self._tasks) >= self._max_pending:
                outcome = "deferred"
            else:
                outcome = "scheduled"
                record = AlertRecord(alert=alert, hits=hits)
                self._records.set(alert.fingerprint, record)
                if key is not None:
                    self._accepted.set(key, None)
                task = asyncio.create_task(self._run(record))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                self._queue.append(alert)
            log = logger.warning if outcome == "deferred" else logger.info
            log(
                "alert received name=%s severity=%s status=%s fingerprint=%s "
                "runbook_hits=%d outcome=%s",
                alert.alertname,
                alert.severity,
                alert.status,
                alert.fingerprint,
                len(hits),
                outcome,
            )
            submissions.append(Submission(alert.fingerprint, outcome, hits, task))
        return submissions

    async def process(self, payload: WebhookPayload) -> list[str]:
        """Submit a group and wait for its background stages to finish."""
        submissions = self.submit(payload)
        tasks = [s.task for s in submissions if s.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return [s.fingerprint for s in submissions]

    async def join(self) -> None:
        """Wait until every background task has finished."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self, timeout: float = 10.0) -> None:
        """Give in-flight alerts ``timeout`` seconds to finish, then cancel them."""
        if not self._tasks:
            return
        _, still_running = await asyncio.wait(list(self._tasks), timeout=timeout)
        for task in still_running:
            task.cancel()
        if still_running:
            logger.warning("cancelled %d unfinished alerts on shutdown", len(still_running))
            await asyncio.gather(*still_running, return_exceptions=True)

    async def _run(self, record: AlertRecord) -> None:
        """Run the slow stages for one alert, bounded by the semaphore."""
        alert = record.alert
        try:
            async with self._semaphore:
                snapshot = await self._correlator.correlate(alert) if self._correlator else None
                record.metrics = snapshot
                diagnosis = await self._diagnose(alert, record.hits, snapshot)
                record.diagnosis = diagnosis
                record.delivered = await self._notify(alert, record.hits, snapshot, diagnosis)
            logger.info(
                "alert processed name=%s fingerprint=%s metric_series=%d diagnosed=%s slack=%s",
                alert.alertname,
                alert.fingerprint,
                len(snapshot.series) if snapshot else 0,
                diagnosis is not None,
                record.delivered,
            )
        except Exception:
            # Nobody awaits this task: log here or the failure is invisible.
            logger.exception(
                "alert processing failed name=%s fingerprint=%s",
                alert.alertname,
                alert.fingerprint,
            )
        finally:
            record.done = True

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

    async def _notify(
        self,
        alert: Alert,
        hits: list[RetrievalHit],
        snapshot: MetricsSnapshot | None,
        diagnosis: Diagnosis | None,
    ) -> bool | None:
        """Run the Slack stage; None when disabled, False when delivery failed."""
        if self._notifier is None:
            return None
        try:
            await self._notifier.notify(alert, hits, snapshot, diagnosis)
        except SlackError as exc:
            logger.warning(
                "slack delivery failed alert=%s fingerprint=%s error=%s",
                alert.alertname,
                alert.fingerprint,
                exc,
            )
            return False
        return True

    def record_for(self, fingerprint: str) -> AlertRecord | None:
        """Return the latest record for a fingerprint (None if unknown or expired)."""
        return self._records.get(fingerprint)

    def retrieval_for(self, fingerprint: str) -> list[RetrievalHit]:
        """Return the runbook hits recorded for an alert fingerprint."""
        record = self._records.get(fingerprint)
        return record.hits if record else []

    def metrics_for(self, fingerprint: str) -> MetricsSnapshot | None:
        """Return the metrics snapshot recorded for an alert fingerprint."""
        record = self._records.get(fingerprint)
        return record.metrics if record else None

    def diagnosis_for(self, fingerprint: str) -> Diagnosis | None:
        """Return the diagnosis recorded for an alert fingerprint."""
        record = self._records.get(fingerprint)
        return record.diagnosis if record else None

    def slack_for(self, fingerprint: str) -> bool | None:
        """Return Slack delivery status for a fingerprint (None when disabled)."""
        record = self._records.get(fingerprint)
        return record.delivered if record else None

    @property
    def in_flight(self) -> int:
        """Alerts whose background stages have not finished yet."""
        return len(self._tasks)

    @property
    def pending(self) -> int:
        return len(self._queue)

    def drain(self) -> list[Alert]:
        """Pop all queued alerts (used by workers and tests)."""
        alerts = list(self._queue)
        self._queue.clear()
        return alerts


def _delivery_key(alert: Alert) -> tuple[str, str, datetime] | None:
    """Identity of one alert occurrence and state; None when it can't be told apart."""
    if not alert.fingerprint:
        return None
    return (alert.fingerprint, alert.status, alert.starts_at)
