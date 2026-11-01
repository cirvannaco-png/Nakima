"""Prometheus metrics and a bounded, redacted in-process log buffer."""
import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime
from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)
webhook_events_total = Counter("nakima_webhook_events_total", "Webhook events handled", ["event_type", "outcome"], registry=REGISTRY)
tasks_total = Counter("nakima_tasks_total", "Orchestration tasks", ["status"], registry=REGISTRY)
task_duration_seconds = Histogram("nakima_task_duration_seconds", "Task duration in seconds", buckets=[30, 60, 120, 300, 600, 1200, 1800], registry=REGISTRY)
provider_call_duration_seconds = Histogram("nakima_provider_call_duration_seconds", "Provider call duration in seconds", ["provider", "action"], registry=REGISTRY)
security_findings_total = Counter("nakima_security_findings_total", "Security findings", ["source", "severity"], registry=REGISTRY)
_LOGS: deque[dict] = deque(maxlen=500)
_LOCK = threading.Lock()
_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token|api[_-]?key|secret|password)(\s*[:=]\s*)[\"']?[^\s,;\"']+"), r"\1\2[REDACTED]"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[REDACTED_GITHUB_TOKEN]"),
)

def redact_log_message(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value[:4000]

class BoundedLogBuffer(logging.Handler):
    """A bounded current-process log ring; no exception tracebacks are copied."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {"timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(), "level": record.levelname, "logger": record.name[:120], "message": redact_log_message(record.getMessage())}
            with _LOCK:
                _LOGS.append(item)
        except Exception:
            self.handleError(record)

def install_log_buffer() -> None:
    root = logging.getLogger()
    if not any(isinstance(handler, BoundedLogBuffer) for handler in root.handlers):
        handler = BoundedLogBuffer()
        handler.setLevel(logging.INFO)
        root.addHandler(handler)

def recent_logs(limit: int = 100) -> list[dict]:
    with _LOCK:
        return list(_LOGS)[-max(1, min(int(limit), 200)):]
