"""Standalone env preflight check.

Usage:
    python scripts/preflight.py

Exits non-zero if required configuration is missing. Intended for CI, docker
entrypoint gates, and pre-deploy smoke checks.
"""

from __future__ import annotations

import sys

from core.config import PreflightError, preflight


def main() -> int:
    try:
        warnings = preflight()
    except PreflightError as exc:
        print(f"[preflight] FAIL\n{exc}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"[preflight] warn: {w}", file=sys.stderr)
    print("[preflight] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
