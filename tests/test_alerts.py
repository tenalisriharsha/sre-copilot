async def test_receive_alerts_accepts_valid_payload(client, alertmanager_payload):
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["received"] == 2
    assert body["fingerprints"] == ["a1b2c3d4e5f60718", "f60718a1b2c3d4e5"]
    assert body["detail"]["receiver"] == "sre-copilot"
    assert body["detail"]["group_status"] == "firing"


async def test_receive_alerts_attaches_metrics_summary(app, client, alertmanager_payload):
    """With a correlator wired, each fingerprint carries a metrics summary."""
    import httpx

    from sre_copilot.metrics.client import PrometheusClient
    from sre_copilot.metrics.correlator import MetricsCorrelator
    from sre_copilot.pipeline import AlertPipeline

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [{"metric": {}, "values": [[1722384000, "0.9"]]}],
                },
            },
        )

    correlator = MetricsCorrelator(
        client=PrometheusClient("http://prometheus:9090", transport=httpx.MockTransport(handler))
    )
    app.state.pipeline = AlertPipeline(retriever=app.state.retriever, correlator=correlator)

    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    metrics = resp.json()["detail"]["metrics"]
    assert set(metrics) == {"a1b2c3d4e5f60718", "f60718a1b2c3d4e5"}
    summary = metrics["a1b2c3d4e5f60718"]
    assert summary["error"] is None
    assert summary["window_minutes"] == 30
    names = [series["name"] for series in summary["series"]]
    assert names == ["cpu_cores", "memory_bytes", "restarts_last_hour"]
    assert summary["series"][0]["latest"] == 0.9


async def test_receive_alerts_metrics_null_when_correlation_disabled(client, alertmanager_payload):
    """Without a Prometheus URL, metrics degrade to null (no failure)."""
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    metrics = resp.json()["detail"]["metrics"]
    assert metrics == {"a1b2c3d4e5f60718": None, "f60718a1b2c3d4e5": None}


async def test_receive_alerts_enqueues_for_processing(client, app, alertmanager_payload):
    await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert app.state.pipeline.pending == 2
    queued = app.state.pipeline.drain()
    assert queued[0].alertname == "KubePodCrashLooping"
    assert queued[0].severity == "critical"
    assert app.state.pipeline.pending == 0


async def test_receive_alerts_attaches_runbook_hits(client, alertmanager_payload):
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    runbooks = resp.json()["detail"]["runbooks"]
    assert set(runbooks) == {"a1b2c3d4e5f60718", "f60718a1b2c3d4e5"}
    top_hit = runbooks["a1b2c3d4e5f60718"][0]
    assert top_hit["runbook"] == "crashloopbackoff"
    assert top_hit["score"] > 0


async def test_receive_alerts_diagnosis_null_when_disabled(client, alertmanager_payload):
    """Without an LLM API key, diagnosis degrades to null (no failure)."""
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    diagnosis = resp.json()["detail"]["diagnosis"]
    assert diagnosis == {"a1b2c3d4e5f60718": None, "f60718a1b2c3d4e5": None}


async def test_receive_alerts_attaches_diagnosis(app, client, alertmanager_payload):
    """With a diagnoser wired, each fingerprint carries the structured diagnosis."""

    from sre_copilot.llm.diagnosis import DiagnosisService
    from sre_copilot.pipeline import AlertPipeline

    class FakeLLMClient:
        async def complete_json(self, *, system: str, user: str) -> str:
            return (
                '{"likely_cause": "bad deploy", "confidence": "medium", '
                '"remediation_steps": ["roll back"]}'
            )

    diagnoser = DiagnosisService(client=FakeLLMClient())
    app.state.pipeline = AlertPipeline(retriever=app.state.retriever, diagnoser=diagnoser)

    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    diagnosis = resp.json()["detail"]["diagnosis"]
    assert set(diagnosis) == {"a1b2c3d4e5f60718", "f60718a1b2c3d4e5"}
    first = diagnosis["a1b2c3d4e5f60718"]
    assert first["likely_cause"] == "bad deploy"
    assert first["confidence"] == "medium"
    assert first["remediation_steps"] == ["roll back"]


async def test_receive_alerts_rejects_invalid_payload(client):
    resp = await client.post("/api/v1/alerts", json={"alerts": [{"labels": {}}]})
    assert resp.status_code == 422


async def test_receive_alerts_accepts_empty_group(client):
    resp = await client.post("/api/v1/alerts", json={"status": "resolved", "alerts": []})
    assert resp.status_code == 202
    assert resp.json()["received"] == 0


async def test_receive_alerts_slack_null_when_notifier_disabled(client, alertmanager_payload):
    """Without a webhook URL, the slack detail degrades to null (no failure)."""
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    slack = resp.json()["detail"]["slack"]
    assert slack == {"a1b2c3d4e5f60718": None, "f60718a1b2c3d4e5": None}


async def test_receive_alerts_reports_slack_delivery(app, client, alertmanager_payload):
    """With a notifier wired, each fingerprint reports its delivery status."""
    from sre_copilot.pipeline import AlertPipeline
    from sre_copilot.slack.notifier import SlackNotifier

    class FakeSlackClient:
        def __init__(self) -> None:
            self.posts: list[dict] = []

        async def post(self, message: dict) -> None:
            self.posts.append(message)

    fake = FakeSlackClient()
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever, notifier=SlackNotifier(client=fake)
    )

    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    slack = resp.json()["detail"]["slack"]
    assert slack == {
        "a1b2c3d4e5f60718": {"delivered": True},
        "f60718a1b2c3d4e5": {"delivered": True},
    }
    assert len(fake.posts) == 2


async def test_receive_alerts_survives_non_prometheus_200(app, client, alertmanager_payload):
    """A proxy/login page answering 200 for Prometheus must not 500 the webhook."""
    import httpx

    from sre_copilot.metrics.client import PrometheusClient
    from sre_copilot.metrics.correlator import MetricsCorrelator
    from sre_copilot.pipeline import AlertPipeline

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>sign in</html>")

    correlator = MetricsCorrelator(
        client=PrometheusClient("http://prometheus:9090", transport=httpx.MockTransport(handler))
    )
    app.state.pipeline = AlertPipeline(retriever=app.state.retriever, correlator=correlator)

    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    summary = resp.json()["detail"]["metrics"]["a1b2c3d4e5f60718"]
    assert summary["series"] == []
    assert "malformed" in summary["error"]
