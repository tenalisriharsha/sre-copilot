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


def test_default_app_works_without_sentence_transformers(monkeypatch):
    """sentence-transformers is an optional extra: the default backend never imports it."""
    import sys

    from sre_copilot.main import create_app
    from sre_copilot.models import Alert

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import -> ImportError
    app = create_app()
    alert = Alert.model_validate(
        {
            "status": "firing",
            "labels": {"alertname": "KubePodCrashLooping"},
            "startsAt": "2026-07-31T02:14:03Z",
        }
    )
    hits = app.state.retriever.retrieve(alert)
    assert hits[0].chunk.runbook == "crashloopbackoff"


def test_sentence_transformers_backend_explains_missing_extra(monkeypatch):
    import sys

    import pytest

    from sre_copilot.rag.embeddings import SentenceTransformerEmbeddingFunction

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match=r"sre-copilot\[embeddings\]"):
        SentenceTransformerEmbeddingFunction()


def test_sentence_transformers_is_an_optional_extra():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    project = pyproject["project"]
    assert not any(dep.startswith("sentence-transformers") for dep in project["dependencies"])
    assert any(
        dep.startswith("sentence-transformers")
        for dep in project["optional-dependencies"]["embeddings"]
    )
