"""Retrieval service: alert in, top-k runbook excerpts out."""

import logging

from sre_copilot.config import Settings
from sre_copilot.models import Alert
from sre_copilot.rag.documents import RetrievalHit
from sre_copilot.rag.embeddings import build_embedding_function
from sre_copilot.rag.loader import load_runbooks
from sre_copilot.rag.store import RunbookStore

logger = logging.getLogger(__name__)


class RunbookRetriever:
    """Finds the runbook sections most relevant to a firing alert."""

    def __init__(self, store: RunbookStore, top_k: int = 3) -> None:
        self._store = store
        self._top_k = top_k

    @classmethod
    def from_settings(cls, settings: Settings) -> "RunbookRetriever":
        """Build a retriever from app settings, indexing runbooks if needed."""
        embedding_function = build_embedding_function(settings)
        store = RunbookStore(
            embedding_function=embedding_function,
            persist_dir=settings.chroma_persist_dir,
        )
        if store.count() == 0:
            chunks = load_runbooks(settings.runbooks_dir)
            store.add(chunks)
            logger.info("runbook index built: %d chunks", store.count())
        else:
            logger.info("runbook index already populated: %d chunks", store.count())
        return cls(store=store, top_k=settings.retrieval_top_k)

    def retrieve(self, alert: Alert, top_k: int | None = None) -> list[RetrievalHit]:
        """Return the top-k runbook hits for an alert (empty if index is empty)."""
        query = self._query_text(alert)
        hits = self._store.query(query, top_k=top_k or self._top_k)
        logger.info(
            "retrieved %d runbook hits for alert=%s fingerprint=%s top=%s",
            len(hits),
            alert.alertname,
            alert.fingerprint,
            hits[0].chunk.id if hits else None,
        )
        return hits

    @staticmethod
    def _query_text(alert: Alert) -> str:
        """Compose the search query from the alert's most informative fields."""
        parts = [
            alert.alertname,
            alert.severity,
            alert.labels.get("namespace", ""),
            alert.labels.get("pod", ""),
            alert.annotations.get("summary", ""),
            alert.annotations.get("description", ""),
        ]
        return " ".join(part for part in parts if part)
