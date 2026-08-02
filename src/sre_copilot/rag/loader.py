"""Load Markdown runbooks from disk and chunk them by section.

Every ``*.md`` file in the runbooks directory becomes one runbook. The file
stem is the runbook name (``crashloopbackoff.md`` → ``crashloopbackoff``),
the first ``#`` heading is the title, and each ``#``/``##`` section becomes
one chunk so retrieval returns focused excerpts instead of whole documents.
"""

import logging
import re
from pathlib import Path

from sre_copilot.rag.documents import RunbookChunk

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$")


def chunk_markdown(name: str, content: str) -> list[RunbookChunk]:
    """Split one Markdown document into section chunks.

    Text before the first heading is indexed as an ``overview`` chunk. Chunks
    keep their heading line so embedded text carries the section context.
    """
    title = name
    sections: list[tuple[str, list[str]]] = []
    current_heading = "overview"
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, current_lines.copy()))

    for line in content.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
            current_heading = heading
            current_lines = [line]
            if match.group(1) == "#":
                title = heading
        else:
            current_lines.append(line)
    flush()

    chunks: list[RunbookChunk] = []
    for index, (heading, lines) in enumerate(sections):
        chunks.append(
            RunbookChunk(
                id=f"{name}::{index}",
                runbook=name,
                title=title,
                section=heading,
                text="\n".join(lines).strip(),
            )
        )
    return chunks


def load_runbooks(runbooks_dir: str | Path) -> list[RunbookChunk]:
    """Load and chunk every Markdown runbook in a directory.

    A missing directory is not an error (the service can start without
    runbooks); it just yields no chunks.
    """
    directory = Path(runbooks_dir)
    if not directory.is_dir():
        logger.warning("runbooks directory %s does not exist; RAG index will be empty", directory)
        return []

    chunks: list[RunbookChunk] = []
    for path in sorted(directory.glob("*.md")):
        file_chunks = chunk_markdown(path.stem, path.read_text(encoding="utf-8"))
        logger.info("loaded runbook %s (%d chunks)", path.stem, len(file_chunks))
        chunks.extend(file_chunks)
    return chunks
