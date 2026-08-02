import math

from sre_copilot.rag.embeddings import HashEmbeddingFunction, tokenize


def _as_lists(embeddings) -> list[list[float]]:
    """ChromaDB's EmbeddingFunction wrapper may return numpy arrays; normalize."""
    return [[float(value) for value in vector] for vector in embeddings]


def test_tokenize_splits_camel_case_identifiers():
    assert tokenize("KubePodCrashLooping") == ["kube", "pod", "crash", "looping"]


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize('Pod payments/api-6d9f7c8b5 "OOMKilled"!') == [
        "pod",
        "payments",
        "api",
        "6d9f7c8b5",
        "oomkilled",
    ]


def test_hash_embeddings_are_deterministic():
    embedder = HashEmbeddingFunction(dimension=64)
    assert _as_lists(embedder(["crash looping pod"])) == _as_lists(embedder(["crash looping pod"]))


def test_hash_embeddings_have_configured_dimension_and_unit_norm():
    embedder = HashEmbeddingFunction(dimension=64)
    (vector,) = _as_lists(embedder(["out of memory killed container"]))
    assert len(vector) == 64
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_hash_embeddings_empty_text_yields_zero_vector():
    embedder = HashEmbeddingFunction(dimension=16)
    (vector,) = _as_lists(embedder([""]))
    assert vector == [0.0] * 16


def test_similar_texts_embed_closer_than_dissimilar_ones():
    embedder = HashEmbeddingFunction()

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    alert, runbook, unrelated = _as_lists(
        embedder(
            [
                "KubePodCrashLooping pod is crash looping",
                "CrashLoopBackOff: the pod keeps crashing and restarting",
                "node disk pressure eviction image garbage collection",
            ]
        )
    )
    assert cosine(alert, runbook) > cosine(alert, unrelated)


def test_invalid_dimension_rejected():
    try:
        HashEmbeddingFunction(dimension=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-positive dimension")
