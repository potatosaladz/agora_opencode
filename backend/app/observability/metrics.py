"""SDK-neutral metric contracts shared by API and database instrumentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

__all__ = ["CounterMetric", "GaugeMetric", "HistogramMetric", "Metrics"]


class CounterMetric(Protocol):
    """Counter operations used by platform instrumentation."""

    def labels(self, *labelvalues: str) -> CounterMetric: ...

    def inc(self, amount: float = 1) -> None: ...


class HistogramMetric(Protocol):
    """Histogram operations used by platform instrumentation."""

    def labels(self, *labelvalues: str) -> HistogramMetric: ...

    def observe(self, amount: float) -> None: ...


class GaugeMetric(Protocol):
    """Gauge operations used by platform instrumentation."""

    def set(self, value: float) -> None: ...


@dataclass(frozen=True, slots=True)
class Metrics:
    """All metric instruments owned by one application instance."""

    registry: object
    http_requests: CounterMetric
    http_latency: HistogramMetric
    db_query_latency: HistogramMetric
    db_transactions: CounterMetric
    port_errors: CounterMetric
    event_publishes: CounterMetric
    readiness: GaugeMetric
    render: Callable[[], tuple[bytes, str]]
