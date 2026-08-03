"""Correlation service: pull recent metrics for the entity an alert fires on."""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from sre_copilot.config import Settings
from sre_copilot.metrics.client import PrometheusClient, PrometheusError
from sre_copilot.metrics.models import MetricSeries, MetricsSnapshot
from sre_copilot.models import Alert

logger = logging.getLogger(__name__)

# Labels copied from the alert into the PromQL selector, in order.
_SELECTOR_LABELS = ("namespace", "pod", "container")

# Friendly name -> PromQL template; ``{selector}`` is filled from alert labels.
QUERIES: dict[str, str] = {
    "cpu_cores": "sum(rate(container_cpu_usage_seconds_total{{{selector}}}[5m]))",
    "memory_bytes": "sum(container_memory_working_set_bytes{{{selector}}})",
    "restarts_last_hour": (
        "sum(increase(kube_pod_container_status_restarts_total{{{selector}}}[1h]))"
    ),
}


class MetricsCorrelator:
    """Queries Prometheus for recent CPU/memory/restart metrics of an alert."""

    def __init__(
        self,
        client: PrometheusClient,
        window_minutes: int = 30,
        step_seconds: int = 60,
    ) -> None:
        self._client = client
        self._window_minutes = window_minutes
        self._step_seconds = step_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "MetricsCorrelator | None":
        """Build a correlator from settings, or None when no URL is configured."""
        if not settings.prometheus_url:
            return None
        client = PrometheusClient(
            settings.prometheus_url,
            timeout=settings.prometheus_timeout_seconds,
        )
        return cls(
            client=client,
            window_minutes=settings.metrics_window_minutes,
            step_seconds=settings.metrics_step_seconds,
        )

    async def correlate(self, alert: Alert) -> MetricsSnapshot:
        """Return recent metrics for the alert's pod/namespace.

        Never raises: alerts without usable labels get an empty snapshot, and
        Prometheus failures produce an empty snapshot with ``error`` set.
        """
        selector = self._selector(alert)
        if selector is None:
            logger.info(
                "no metric labels on alert=%s fingerprint=%s, skipping correlation",
                alert.alertname,
                alert.fingerprint,
            )
            return MetricsSnapshot(window_minutes=self._window_minutes)

        end = datetime.now(UTC)
        start = end - timedelta(minutes=self._window_minutes)
        series: list[MetricSeries] = []
        for name, template in QUERIES.items():
            query = template.format(selector=selector)
            try:
                result = await self._client.query_range(query, start, end, self._step_seconds)
            except (httpx.HTTPError, PrometheusError) as exc:
                logger.warning(
                    "prometheus query failed alert=%s name=%s error=%s",
                    alert.alertname,
                    name,
                    exc,
                )
                return MetricsSnapshot(window_minutes=self._window_minutes, error=str(exc))
            series.extend(MetricSeries(name=name, query=query, points=hit.points) for hit in result)

        logger.info(
            "correlated alert=%s fingerprint=%s series=%d window=%dm",
            alert.alertname,
            alert.fingerprint,
            len(series),
            self._window_minutes,
        )
        return MetricsSnapshot(window_minutes=self._window_minutes, series=tuple(series))

    @staticmethod
    def _selector(alert: Alert) -> str | None:
        """Build a PromQL label selector from the alert's identifying labels."""
        pairs = [
            f'{key}="{alert.labels[key]}"' for key in _SELECTOR_LABELS if alert.labels.get(key)
        ]
        return ", ".join(pairs) if pairs else None
