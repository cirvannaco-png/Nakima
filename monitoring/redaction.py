from __future__ import annotations

import re

_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token|api[_-]?key|password|secret)(\s*[:=]\s*)[^\s,;]+"), r"\1\2[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
)


def redact_sensitive_text(value: str, limit: int = 4_000) -> str:
    """Bound and redact common credential forms before logs or telemetry."""
    text = value[: max(0, limit)]
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
