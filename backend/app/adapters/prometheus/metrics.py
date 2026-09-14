"""Prometheus implementation of the platform's SDK-neutral metric contracts."""

from __future__ import annotations

from typing import cast

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest

from app.observability.metrics import CounterMetric, GaugeMetric, HistogramMetric, Metrics

__all__ = ["EVENT_PUBLISHES", "build_metrics"]


def build_metrics(registry: CollectorRegistry | None = None) -> Metrics:
    """Create a complete collector set without leaking Prometheus types across the adapter."""
    target = registry or CollectorRegistry(auto_describe=True)
    http_requests = Counter(
        "agora_http_requests_total",
        "HTTP requests by route template, method, and status",
        ["method", "route", "status"],
        registry=target,
    )
    http_latency = Histogram(
        "agora_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "route"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        registry=target,
    )
    db_query_latency = Histogram(
        "agora_db_query_duration_seconds",
        "Database query latency by operation and outcome",
        ["operation", "outcome"],
        buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
        registry=target,
    )
    db_transactions = Counter(
        "agora_db_transactions_total",
        "Database transactions by outcome",
        ["outcome"],
        registry=target,
    )
    port_errors = Counter(
        "agora_port_errors_total",
        "Adapter failures by port and transience",
        ["port", "kind"],
        registry=target,
    )
    event_publishes = Counter(
        "agora_event_publishes_total",
        "Event bus publishes by outcome",
        ["subject", "outcome"],
        registry=target,
    )
    readiness = Gauge(
        "agora_ready",
        "1 when every required dependency is reachable, 0 otherwise",
        registry=target,
    )
    return Metrics(
        registry=target,
        http_requests=cast(CounterMetric, http_requests),
        http_latency=cast(HistogramMetric, http_latency),
        db_query_latency=cast(HistogramMetric, db_query_latency),
        db_transactions=cast(CounterMetric, db_transactions),
        port_errors=cast(CounterMetric, port_errors),
        event_publishes=cast(CounterMetric, event_publishes),
        readiness=cast(GaugeMetric, readiness),
        render=lambda: (generate_latest(target), CONTENT_TYPE_LATEST),
    )


# Compatibility collector for adapters not constructed by the HTTP app factory.
EVENT_PUBLISHES = build_metrics(REGISTRY).event_publishes
