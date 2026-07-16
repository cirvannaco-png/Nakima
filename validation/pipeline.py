import re
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

from execution.sandbox import SandboxExecutor


class Failure(TypedDict):
    step: str
    command: str
    log: str
    file: Optional[str]
    line: Optional[int]


# flake8: "path/to/file.py:12:5: E302 expected 2 blank lines, got 1"
FLAKE8_RE = re.compile(r"^(?P<file>[^\s:][^:]*\.py):(?P<line>\d+):\d+:", re.MULTILINE)

# pytest short failure summary: "FAILED tests/test_foo.py::test_bar - AssertionError: ..."
PYTEST_SUMMARY_RE = re.compile(r"^FAILED\s+(?P<file>\S+\.py)(::\S+)?", re.MULTILINE)

# pytest traceback frame: 'tests/test_foo.py:23: in test_bar'
PYTEST_TRACEBACK_RE = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+): in ", re.MULTILINE)

# black --check: "would reformat path/to/file.py"
BLACK_RE = re.compile(r"^(?:would reformat|reformatted)\s+(?P<file>\S+\.py)", re.MULTILINE)


def _extract_file_and_line(step_name: str, logs: str) -> tuple[Optional[str], Optional[int]]:
    """Best-effort extraction of the offending file (and line, where available)
    from a tool's raw output, per tool's output format."""
    patterns = {
        "lint": [FLAKE8_RE],
        "test": [PYTEST_SUMMARY_RE, PYTEST_TRACEBACK_RE],
        "format": [BLACK_RE],
    }.get(step_name, [FLAKE8_RE, PYTEST_SUMMARY_RE, PYTEST_TRACEBACK_RE, BLACK_RE])

    for pattern in patterns:
        match = pattern.search(logs)
        if match:
            file = match.group("file")
            line = int(match.group("line")) if "line" in match.groupdict() and match.group("line") else None
            return file, line
    return None, None


class ValidationPipeline:
    def __init__(self):
        self.executor = SandboxExecutor()

    async def validate(self, repo_dir: Path, language: str = "python") -> Dict:
        """Run format/lint/build/test in sequence. Stops at the first failing
        step (no point running tests if the build itself is broken) and
        returns structured failure info the debug agent can act on directly."""
        steps = {
            "format": ["black --check ."],
            "lint": ["flake8 ."],
            "build": ["pip install -e ."],
            "test": ["pytest -x"],
        }
        failures: List[Failure] = []
        for step_name, commands in steps.items():
            result = await self.executor.run_build(repo_dir, commands)
            if not result["success"]:
                file, line = _extract_file_and_line(step_name, result["logs"])
                failures.append(
                    Failure(
                        step=step_name,
                        command=result["command"],
                        log=result["logs"],
                        file=file,
                        line=line,
                    )
                )
                break  # don't cascade — fix this before running later steps
        return {"success": len(failures) == 0, "failures": failures}
