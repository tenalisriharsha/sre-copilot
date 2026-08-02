import pytest
from httpx import ASGITransport, AsyncClient

from sre_copilot.config import get_settings
from sre_copilot.main import create_app


@pytest.fixture(scope="session", autouse=True)
def _isolated_chroma_dir(tmp_path_factory):
    """Point the Chroma persist dir at a throwaway tmp dir for the test run."""
    import os

    os.environ["SRE_COPILOT_CHROMA_PERSIST_DIR"] = str(tmp_path_factory.mktemp("chroma"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def alertmanager_payload() -> dict:
    """A realistic Alertmanager v4 webhook payload."""
    return {
        "version": "4",
        "groupKey": '{}:{alertname="KubePodCrashLooping", namespace="payments"}',
        "status": "firing",
        "receiver": "sre-copilot",
        "groupLabels": {"alertname": "KubePodCrashLooping", "namespace": "payments"},
        "commonLabels": {
            "alertname": "KubePodCrashLooping",
            "namespace": "payments",
            "severity": "critical",
        },
        "commonAnnotations": {"summary": "Pod is crash looping"},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "namespace": "payments",
                    "pod": "payments-api-6d9f7c8b5-x2v4k",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Pod payments/payments-api-6d9f7c8b5-x2v4k is crash looping",
                    "runbook_url": "https://runbooks.example.com/crashloopbackoff",
                },
                "startsAt": "2026-07-31T02:14:03.000Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus:9090/graph?g0.expr=...",
                "fingerprint": "a1b2c3d4e5f60718",
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "namespace": "payments",
                    "pod": "payments-worker-5c4f9d7f6b-q8w2j",
                    "severity": "warning",
                },
                "annotations": {"summary": "Pod payments/payments-worker is crash looping"},
                "startsAt": "2026-07-31T02:16:41.000Z",
                "fingerprint": "f60718a1b2c3d4e5",
            },
        ],
    }
