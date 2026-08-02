"""ChromaDB-backed vector store for runbook chunks."""

import logging

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction

from sre_copilot.rag.documents import RetrievalHit, RunbookChunk

logger = logging.getLogger(__name__)


class RunbookStore:
    """A ChromaDB collection holding embedded runbook chunks.

    Pass ``persist_dir`` for a durable on-disk index (production) or a
    pre-built ``client`` (tests use ``chromadb.EphemeralClient()``).
    """

    def __init__(
        self,
        embedding_function: EmbeddingFunction[Documents],
        persist_dir: str | None = None,
        client: chromadb.ClientAPI | None = None,
        collection_name: str = "runbooks",
    ) -> None:
        settings = chromadb.Settings(anonymized_telemetry=False)
        if client is not None:
            self._client = client
        elif persist_dir is not None:
            self._client = chromadb.PersistentClient(path=persist_dir, settings=settings)
        else:
            self._client = chromadb.EphemeralClient(settings=settings)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self._collection.count()

    def add(self, chunks: list[RunbookChunk]) -> None:
        """Upsert chunks into the collection."""
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {"runbook": chunk.runbook, "title": chunk.title, "section": chunk.section}
                for chunk in chunks
            ],
        )
        logger.info("indexed %d runbook chunks (total: %d)", len(chunks), self.count())

    def query(self, text: str, top_k: int = 3) -> list[RetrievalHit]:
        """Return the ``top_k`` chunks most similar to ``text``."""
        if self.count() == 0:
            return []
        results = self._collection.query(
            query_texts=[text],
            n_results=min(top_k, self.count()),
            include=["documents", "metadatas", "distances"],
        )
        hits: list[RetrievalHit] = []
        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            chunk = RunbookChunk(
                id=chunk_id,
                runbook=metadata["runbook"],
                title=metadata["title"],
                section=metadata["section"],
                text=document,
            )
            # With cosine space, distance = 1 - cosine similarity.
            hits.append(RetrievalHit(chunk=chunk, score=1.0 - distance))
        return hits
