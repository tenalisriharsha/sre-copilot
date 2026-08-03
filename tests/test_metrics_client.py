"""Tests for the Prometheus HTTP API client (mocked transport, no live server)."""

from datetime import UTC, datetime

import httpx
import pytest

from sre_copilot.metrics.client import PrometheusClient, PrometheusError

MATRIX_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"__name__": "up", "pod": "payments-api-x2v4k"},
                "values": [[1722384000, "0.42"], [1722384060, "0.43"]],
            },
            {
                "metric": {"pod": "payments-api-q8w2j"},
                "values": [[1722384000, "1"]],
            },
        ],
    },
}

START = datetime(2026, 7, 31, 2, 0, 0, tzinfo=UTC)
END = datetime(2026, 7, 31, 2, 30, 0, tzinfo=UTC)


def make_client(handler) -> PrometheusClient:
    return PrometheusClient(
        "http://prometheus:9090/",
        transport=httpx.MockTransport(handler),
    )


async def test_query_range_parses_matrix_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query_range"
        params = request.url.params
        assert params["query"] == "up"
        assert float(params["start"]) == START.timestamp()
        assert float(params["end"]) == END.timestamp()
        assert params["step"] == "60"
        return httpx.Response(200, json=MATRIX_RESPONSE)

    client = make_client(handler)
    series = await client.query_range("up", START, END, 60)
    await client.aclose()

    assert len(series) == 2
    first = series[0]
    assert first.name == "up"
    assert first.query == "up"
    assert len(first.points) == 2
    assert first.points[0].timestamp == 1722384000.0
    assert first.points[0].value == 0.42
    assert first.latest_value == 0.43
    # Series without __name__ falls back to a label summary.
    assert series[1].name == "pod=payments-api-q8w2j"
    assert series[1].latest_value == 1.0


async def test_query_range_empty_result():
    client = make_client(
        lambda request: httpx.Response(
            200, json={"status": "success", "data": {"resultType": "matrix", "result": []}}
        )
    )
    assert await client.query_range("up", START, END, 60) == []
    await client.aclose()


async def test_query_range_raises_on_prometheus_error_payload():
    client = make_client(
        lambda request: httpx.Response(
            400,
            json={
                "status": "error",
                "errorType": "bad_data",
                "error": "invalid parameter 'query'",
            },
        )
    )
    with pytest.raises(PrometheusError, match="invalid parameter 'query'"):
        await client.query_range("not valid promql", START, END, 60)
    await client.aclose()


async def test_query_range_raises_on_http_error():
    client = make_client(lambda request: httpx.Response(502, text="bad gateway"))
    with pytest.raises(httpx.HTTPStatusError):
        await client.query_range("up", START, END, 60)
    await client.aclose()


async def test_query_range_propagates_connection_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    client = make_client(handler)
    with pytest.raises(httpx.ConnectError):
        await client.query_range("up", START, END, 60)
    await client.aclose()
