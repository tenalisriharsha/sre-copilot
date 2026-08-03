"""Async client for the Prometheus HTTP API (``/api/v1/query_range``)."""

from datetime import datetime
from typing import Any

import httpx

from sre_copilot.metrics.models import MetricPoint, MetricSeries


class PrometheusError(Exception):
    """Raised when Prometheus answers with a non-success status payload."""


class PrometheusClient:
    """Thin async wrapper around the Prometheus range-query endpoint."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[MetricSeries]:
        """Run a range query and parse the matrix result into series.

        Raises ``httpx.HTTPError`` on transport/HTTP failures and
        ``PrometheusError`` when the API reports an error payload.
        """
        resp = await self._client.get(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
            },
        )
        # Prometheus reports query errors as an HTTP 4xx whose JSON body has
        # "status": "error" — surface those as PrometheusError, everything
        # else (5xx, non-JSON) as httpx.HTTPStatusError.
        payload: dict[str, Any] = {}
        if resp.headers.get("content-type", "").startswith("application/json"):
            payload = resp.json()
        if payload.get("status") == "error":
            raise PrometheusError(payload.get("error", "unknown prometheus error"))
        resp.raise_for_status()
        return [self._parse_series(item, query) for item in payload["data"].get("result", [])]

    @staticmethod
    def _parse_series(item: dict[str, Any], query: str) -> MetricSeries:
        metric = item.get("metric", {})
        name = metric.get("__name__", "") or ",".join(
            f"{key}={value}" for key, value in sorted(metric.items())
        )
        points = tuple(
            MetricPoint(timestamp=float(ts), value=float(value))
            for ts, value in item.get("values", [])
        )
        return MetricSeries(name=name or "series", query=query, points=points)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
