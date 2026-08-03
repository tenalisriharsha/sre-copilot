"""Data structures shared across the metrics correlation stage."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricPoint:
    """One sample of a time series."""

    timestamp: float  # unix epoch seconds
    value: float


@dataclass(frozen=True)
class MetricSeries:
    """A named time series returned by a range query."""

    name: str  # friendly name (e.g. "cpu_cores") or Prometheus metric name
    query: str  # the PromQL expression that produced this series
    points: tuple[MetricPoint, ...] = field(default_factory=tuple)

    @property
    def latest_value(self) -> float | None:
        """Most recent sample value, or None for an empty series."""
        return self.points[-1].value if self.points else None


@dataclass(frozen=True)
class MetricsSnapshot:
    """The metrics correlated with one alert over a recent time window.

    ``error`` is set when Prometheus could not be queried — the snapshot is
    then empty but still returned so the pipeline degrades gracefully.
    """

    window_minutes: int
    series: tuple[MetricSeries, ...] = field(default_factory=tuple)
    error: str | None = None
