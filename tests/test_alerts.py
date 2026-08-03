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


async def test_receive_alerts_rejects_invalid_payload(client):
    resp = await client.post("/api/v1/alerts", json={"alerts": [{"labels": {}}]})
    assert resp.status_code == 422


async def test_receive_alerts_accepts_empty_group(client):
    resp = await client.post("/api/v1/alerts", json={"status": "resolved", "alerts": []})
    assert resp.status_code == 202
    assert resp.json()["received"] == 0
