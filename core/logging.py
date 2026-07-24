"""JSON structured logging for Nakima.

Emits one JSON object per log record on stdout so log aggregators
(Datadog, Loki, CloudWatch, GCP Logging) can index fields directly.
Set LOG_FORMAT=text to fall back to human-readable logs in dev.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from core.config import settings


class JsonFormatter(logging.Formatter):
    """Format LogRecord as a single-line JSON document."""

    RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Attach any structured extras passed via logger.info("...", extra={...})
        for key, value in record.__dict__.items():
            if key in self.RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Configure root logging based on ENVIRONMENT / LOG_FORMAT."""
    level = logging.INFO if settings.ENVIRONMENT == "production" else logging.DEBUG
    log_format = (getattr(settings, "LOG_FORMAT", None) or "json").lower()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Align uvicorn's loggers with our formatter so access logs are JSON too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
