"""Read-only team guidance loaded from a repository's default branch."""
from pathlib import Path
GUIDANCE_RELATIVE_PATH = Path(".nakima") / "workspace-guidance.md"
MAX_GUIDANCE_CHARS = 16000

def load_approved_workspace_guidance(repo_dir: str | Path) -> str:
    """Read version-controlled guidance; never promote unreviewed model guesses."""
    root = Path(repo_dir).resolve()
    directory = root / GUIDANCE_RELATIVE_PATH.parent
    path = root / GUIDANCE_RELATIVE_PATH
    try:
        if directory.is_symlink() or path.is_symlink() or not path.is_file():
            return ""
        resolved = path.resolve(strict=True)
        if root not in resolved.parents:
            return ""
        return path.read_text(encoding="utf-8")[:MAX_GUIDANCE_CHARS].strip()
    except (OSError, UnicodeError, RuntimeError):
        return ""
