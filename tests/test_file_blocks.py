from pathlib import Path

import pytest

from utils.file_blocks import apply_file_changes, parse_file_blocks

SAMPLE_RESPONSE = """
Here are the changes:

### FILE: app/routes.py
```python
def hello():
    return "hi"
```
### END FILE

### FILE: app/utils.py
```python
def add(a, b):
    return a + b
```
### END FILE

### FILE: old_module.py DELETE
### END FILE
"""


def test_parse_file_blocks_extracts_all_changes():
    changes = parse_file_blocks(SAMPLE_RESPONSE)
    by_path = {c.path: c for c in changes}
    assert by_path["app/routes.py"].content.strip() == 'def hello():\n    return "hi"'
    assert by_path["app/utils.py"].content is not None
    assert by_path["old_module.py"].content is None


def test_parse_file_blocks_no_matches_returns_empty():
    assert parse_file_blocks("no file blocks here at all") == []


def test_apply_file_changes_writes_and_deletes(tmp_path: Path):
    (tmp_path / "old_module.py").write_text("# old")
    changes = parse_file_blocks(SAMPLE_RESPONSE)
    touched = apply_file_changes(tmp_path, changes)

    assert set(touched) == {"app/routes.py", "app/utils.py", "old_module.py"}
    assert (tmp_path / "app/routes.py").exists()
    assert not (tmp_path / "old_module.py").exists()


def test_apply_file_changes_blocks_path_traversal(tmp_path: Path):
    from utils.file_blocks import FileChange

    malicious = [FileChange(path="../../etc/passwd", content="pwned")]
    with pytest.raises(ValueError):
        apply_file_changes(tmp_path, malicious)
