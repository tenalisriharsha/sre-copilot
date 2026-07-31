async def test_receive_alerts_accepts_valid_payload(client, alertmanager_payload):
    resp = await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["received"] == 2
    assert body["fingerprints"] == ["a1b2c3d4e5f60718", "f60718a1b2c3d4e5"]
    assert body["detail"]["receiver"] == "sre-copilot"
    assert body["detail"]["group_status"] == "firing"


async def test_receive_alerts_enqueues_for_processing(client, app, alertmanager_payload):
    await client.post("/api/v1/alerts", json=alertmanager_payload)
    assert app.state.pipeline.pending == 2
    queued = app.state.pipeline.drain()
    assert queued[0].alertname == "KubePodCrashLooping"
    assert queued[0].severity == "critical"
    assert app.state.pipeline.pending == 0


async def test_receive_alerts_rejects_invalid_payload(client):
    resp = await client.post("/api/v1/alerts", json={"alerts": [{"labels": {}}]})
    assert resp.status_code == 422


async def test_receive_alerts_accepts_empty_group(client):
    resp = await client.post("/api/v1/alerts", json={"status": "resolved", "alerts": []})
    assert resp.status_code == 202
    assert resp.json()["received"] == 0
