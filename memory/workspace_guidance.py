"""Read approved, version-controlled workspace guidance."""
from pathlib import Path
GUIDANCE_PATH=Path('.nakima')/'workspace-guidance.md'
def load_approved_workspace_guidance(repo_dir: str|Path)->str:
    root=Path(repo_dir).resolve(); parent=root/GUIDANCE_PATH.parent; path=root/GUIDANCE_PATH
    try:
        if parent.is_symlink() or path.is_symlink() or not path.is_file(): return ''
        resolved=path.resolve(strict=True)
        if root not in resolved.parents: return ''
        return path.read_text(encoding='utf-8')[:16000].strip()
    except (OSError,UnicodeError,RuntimeError): return ''
