from __future__ import annotations

from pathlib import Path

GUIDANCE_PATH = Path(".nakima/workspace-guidance.md")
MAX_GUIDANCE_BYTES = 16_384


def load_approved_guidance(repository_root: str | Path) -> str:
    """Load only the explicitly approved, version-controlled guidance file.

    Missing, oversized, non-UTF-8, or symlinked guidance is ignored. The
    caller must still treat the returned text as untrusted project data and
    keep system/developer instructions higher priority.
    """
    root = Path(repository_root).resolve()
    candidate = root / GUIDANCE_PATH
    try:
        if candidate.is_symlink():
            return ""
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return ""
        if resolved.stat().st_size > MAX_GUIDANCE_BYTES:
            return ""
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError):
        return ""
