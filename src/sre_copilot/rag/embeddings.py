"""Embedding providers for the runbook vector store.

Two backends:

- ``HashEmbeddingFunction`` — deterministic bag-of-words hashing embedder.
  No model download, no GPU, works offline; the default so local dev and CI
  never touch the network. Good enough for keyword-heavy runbook matching.
- ``SentenceTransformerEmbeddingFunction`` — real local embeddings via
  sentence-transformers (loaded lazily so the dependency is only imported
  when selected).

Both implement ChromaDB's ``EmbeddingFunction`` protocol.
"""

import hashlib
import math
import re
from typing import Any

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space

from sre_copilot.config import Settings

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, breaking up CamelCase identifiers.

    Alert and runbook vocabulary is full of identifiers like
    ``KubePodCrashLooping``; splitting them into ``kube pod crash looping``
    is what makes keyword overlap between alerts and runbooks work.
    """
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", text)
    return _TOKEN_RE.findall(spaced.lower())


class HashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic hashing embedder (signed feature hashing, L2-normalized)."""

    def __init__(self, dimension: int = 384) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed(text) for text in input]

    @staticmethod
    def name() -> str:
        return "sre-copilot-hash"

    def default_space(self) -> Space:
        return "cosine"

    def supported_spaces(self) -> list[Space]:
        return ["cosine"]

    def get_config(self) -> dict[str, Any]:
        return {"dimension": self.dimension}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashEmbeddingFunction":
        return HashEmbeddingFunction(dimension=config.get("dimension", 384))

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4]) % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(value * value for value in vec))
        if norm > 0:
            vec = [value / norm for value in vec]
        return vec


class SentenceTransformerEmbeddingFunction(EmbeddingFunction[Documents]):
    """Local sentence-transformers embeddings (model loaded on construction)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self._model.encode(list(input), normalize_embeddings=True)
        return embeddings.tolist()

    @staticmethod
    def name() -> str:
        return "sre-copilot-sentence-transformers"

    def default_space(self) -> Space:
        return "cosine"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "SentenceTransformerEmbeddingFunction":
        return SentenceTransformerEmbeddingFunction(model_name=config["model_name"])


def build_embedding_function(settings: Settings) -> EmbeddingFunction[Documents]:
    """Create the embedding function selected by ``settings.embedding_backend``."""
    if settings.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbeddingFunction(settings.embedding_model)
    return HashEmbeddingFunction()
