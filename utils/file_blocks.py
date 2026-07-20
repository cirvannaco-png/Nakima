"""
Parses the "### FILE: path" / "### END FILE" convention (see
providers.implementations.claude.FILE_BLOCK_INSTRUCTIONS) out of a raw AI
response and turns it into a list of concrete filesystem writes.

This replaces the original stub, which just wrote the entire raw AI response
into a single hardcoded `nakima_generated.py` file regardless of how many
files were actually supposed to change or what language they were in.
"""

import re
from dataclasses import dataclass
from pathlib import Path

FILE_BLOCK_RE = re.compile(
    r"###\s*FILE:\s*(?P<path>\S+)\s*\n" r"```[a-zA-Z0-9_+-]*\n" r"(?P<body>.*?)" r"\n```\s*\n" r"###\s*END FILE",
    re.DOTALL,
)

DELETE_BLOCK_RE = re.compile(
    r"###\s*FILE:\s*(?P<path>\S+)\s+DELETE\s*\n" r"###\s*END FILE",
)


@dataclass
class FileChange:
    path: str
    content: str | None  # None means "delete this file"


def parse_file_blocks(response_text: str) -> list[FileChange]:
    """Extract FileChange entries from an AI response.

    Falls back to returning an empty list (not a crash) if the model didn't
    follow the format — callers should treat that as "nothing to apply" and
    surface it, rather than silently writing garbage to disk.
    """
    changes: list[FileChange] = []
    seen_paths: set[str] = set()

    for match in DELETE_BLOCK_RE.finditer(response_text):
        path = match.group("path").strip()
        changes.append(FileChange(path=path, content=None))
        seen_paths.add(path)

    for match in FILE_BLOCK_RE.finditer(response_text):
        path = match.group("path").strip()
        if path in seen_paths:
            continue
        body = match.group("body")
        changes.append(FileChange(path=path, content=body))
        seen_paths.add(path)

    return changes


def apply_file_changes(repo_dir: Path, changes: list[FileChange]) -> list[str]:
    """Writes/deletes files on disk. Returns the list of paths (relative to
    repo_dir, as strings) that were modified, for use in `git add` / commit."""
    touched: list[str] = []
    for change in changes:
        target = (repo_dir / change.path).resolve()
        # Guard against path traversal from a misbehaving model response.
        if not str(target).startswith(str(repo_dir.resolve())):
            raise ValueError(f"Refusing to write outside repo_dir: {change.path}")

        if change.content is None:
            if target.exists():
                target.unlink()
            touched.append(change.path)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content)
        touched.append(change.path)

    return touched
