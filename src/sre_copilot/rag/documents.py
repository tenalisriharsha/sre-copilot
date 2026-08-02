"""Data structures shared across the RAG pipeline."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunbookChunk:
    """One searchable section of a runbook."""

    id: str
    runbook: str  # runbook name (markdown file stem, e.g. "crashloopbackoff")
    title: str  # runbook title (first-level heading)
    section: str  # section heading this chunk came from ("overview" for preamble)
    text: str  # chunk body, including the section heading
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    """A chunk returned by the vector store, with its similarity score."""

    chunk: RunbookChunk
    score: float  # cosine similarity in [-1, 1]; higher is better
