from datetime import UTC, datetime

import chromadb
import pytest

from sre_copilot.config import Settings
from sre_copilot.models import Alert
from sre_copilot.rag.embeddings import HashEmbeddingFunction
from sre_copilot.rag.loader import load_runbooks
from sre_copilot.rag.retriever import RunbookRetriever
from sre_copilot.rag.store import RunbookStore

RUNBOOKS_DIR = "runbooks"  # the repo's sample runbooks


def make_alert(alertname: str, summary: str, **labels: str) -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": alertname, "severity": "critical", **labels},
        annotations={"summary": summary},
        startsAt=datetime(2026, 7, 31, 2, 14, 3, tzinfo=UTC),
        fingerprint="test-fingerprint",
    )


@pytest.fixture
def store() -> RunbookStore:
    store = RunbookStore(
        embedding_function=HashEmbeddingFunction(),
        client=chromadb.EphemeralClient(),
    )
    store.add(load_runbooks(RUNBOOKS_DIR))
    return store


@pytest.fixture
def retriever(store) -> RunbookRetriever:
    return RunbookRetriever(store=store, top_k=3)


def test_store_indexes_sample_runbooks(store):
    # 5 runbooks, each with a title section plus several ## sections.
    assert store.count() > 15


def test_crashloop_alert_retrieves_crashloop_runbook(retriever):
    alert = make_alert(
        "KubePodCrashLooping",
        "Pod payments/payments-api-6d9f7c8b5-x2v4k is crash looping",
        namespace="payments",
        pod="payments-api-6d9f7c8b5-x2v4k",
    )
    hits = retriever.retrieve(alert)
    assert hits
    assert hits[0].chunk.runbook == "crashloopbackoff"
    assert hits[0].score > 0


def test_oomkilled_alert_retrieves_oomkilled_runbook(retriever):
    alert = make_alert(
        "OOMKilled",
        "Container payments-worker was OOM killed, memory limit exceeded",
        namespace="payments",
        pod="payments-worker-5c4f9d7f6b-q8w2j",
    )
    hits = retriever.retrieve(alert)
    assert hits
    assert hits[0].chunk.runbook == "oomkilled"


def test_retrieve_respects_top_k(retriever):
    alert = make_alert("KubePodCrashLooping", "pod crash looping")
    hits = retriever.retrieve(alert, top_k=2)
    assert len(hits) == 2


def test_hits_are_sorted_by_descending_score(retriever):
    alert = make_alert("ImagePullBackOff", "failed to pull container image")
    scores = [hit.score for hit in retriever.retrieve(alert)]
    assert scores == sorted(scores, reverse=True)


def test_empty_store_returns_no_hits():
    store = RunbookStore(
        embedding_function=HashEmbeddingFunction(),
        client=chromadb.EphemeralClient(),
        collection_name="empty-runbooks",
    )
    retriever = RunbookRetriever(store=store)
    alert = make_alert("KubePodCrashLooping", "pod crash looping")
    assert retriever.retrieve(alert) == []


def test_from_settings_builds_and_indexes(tmp_path):
    settings = Settings(
        chroma_persist_dir=str(tmp_path / "chroma"),
        runbooks_dir=RUNBOOKS_DIR,
        embedding_backend="hash",
    )
    retriever = RunbookRetriever.from_settings(settings)
    alert = make_alert("KubeNodeNotReady", "node worker-3 is NotReady")
    hits = retriever.retrieve(alert)
    assert hits
    assert hits[0].chunk.runbook == "kube-node-not-ready"

    # A second retriever over the same persist dir reuses the index.
    retriever2 = RunbookRetriever.from_settings(settings)
    assert retriever2.retrieve(alert)[0].chunk.runbook == "kube-node-not-ready"
