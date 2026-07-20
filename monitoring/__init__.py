"""Nakima observability — Prometheus metrics + OpenTelemetry tracing.

Metrics are exported via prometheus-client's built-in HTTP server and also
available to the FastAPI process through the shared registry. The trace
provider is configured once at import time so any module can acquire a
tracer with `opentelemetry.trace.get_tracer(__name__)` without additional
setup.

Design choices:
- A single `CollectorRegistry` instance (REGISTRY) is used everywhere so
  metrics can be gathered in-process without starting a separate HTTP
  server (useful in tests where starting a real server is impractical).
- Tracing falls back gracefully: if the OTLP endpoint is not configured
  (typical in development) spans are exported to stdout at DEBUG level via
  ConsoleSpanExporter, never silently dropped.
"""

import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import CollectorRegistry, Counter, Histogram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared Prometheus registry
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry(auto_describe=True)

# Total webhook events received, labelled by event type and outcome.
webhook_events_total = Counter(
    "nakima_webhook_events_total",
    "Total GitHub webhook events received by Nakima",
    labelnames=["event_type", "outcome"],
    registry=REGISTRY,
)

# Total orchestration tasks, labelled by final status (success/failed/pending).
tasks_total = Counter(
    "nakima_tasks_total",
    "Total orchestration tasks created by Nakima",
    labelnames=["status"],
    registry=REGISTRY,
)

# End-to-end task processing latency (seconds).
task_duration_seconds = Histogram(
    "nakima_task_duration_seconds",
    "End-to-end latency for orchestration tasks (seconds)",
    buckets=[30, 60, 120, 300, 600, 1200, 1800],
    registry=REGISTRY,
)

# Sandbox execution latency (seconds).
sandbox_run_duration_seconds = Histogram(
    "nakima_sandbox_run_duration_seconds",
    "Latency of sandbox container runs (seconds)",
    labelnames=["stage"],
    buckets=[5, 15, 30, 60, 120, 300],
    registry=REGISTRY,
)

# AI provider call latency (seconds).
provider_call_duration_seconds = Histogram(
    "nakima_provider_call_duration_seconds",
    "Latency of AI provider API calls (seconds)",
    labelnames=["provider", "action"],
    buckets=[1, 2, 5, 10, 30, 60],
    registry=REGISTRY,
)

# NSIL security scan results.
security_findings_total = Counter(
    "nakima_security_findings_total",
    "Total security findings detected by NSIL scanners",
    labelnames=["source", "severity"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# OpenTelemetry tracer provider
# ---------------------------------------------------------------------------

_SERVICE_NAME = "nakima"

_resource = Resource.create({"service.name": _SERVICE_NAME})
_provider = TracerProvider(resource=_resource)

_otlp_endpoint = os.getenv("OTLP_ENDPOINT")
if _otlp_endpoint:
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[import]

        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint)))
        logger.info(f"OpenTelemetry: exporting traces to {_otlp_endpoint}")
    except ImportError:
        logger.warning(
            "OTLP_ENDPOINT is set but opentelemetry-exporter-otlp-proto-grpc is not installed; "
            "falling back to ConsoleSpanExporter"
        )
        _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
else:
    # Development / CI: print spans to stdout at DEBUG level so they're
    # visible when LOG_LEVEL=DEBUG without polluting normal output.
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(_provider)

# Convenience accessor — callers should use this rather than
# opentelemetry.trace.get_tracer() directly so they get the right provider.
def get_tracer(name: str = _SERVICE_NAME):
    """Return a tracer scoped to `name` (use ``__name__`` at the call site)."""
    return trace.get_tracer(name)
