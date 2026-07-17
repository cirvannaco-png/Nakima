import re
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

from execution.sandbox import SandboxExecutor
from execution.tool_registry import ToolRegistry


class Failure(TypedDict):
    stage: str
    command: str
    log: str
    file: Optional[str]
    line: Optional[int]


# Best-effort file/line extraction per (language, stage). Order matters —
# first match wins. These are heuristics against each tool's default
# output format, not guarantees; a failure with no match is still
# reported, just without a `file`/`line`, and the debug agent falls back
# to working from the raw log.
EXTRACTION_PATTERNS: Dict[str, Dict[str, List[re.Pattern]]] = {
    "python": {
        "format": [re.compile(r"^(?:would reformat|reformatted)\s+(?P<file>\S+\.py)", re.MULTILINE)],
        "lint": [re.compile(r"^(?P<file>[^\s:][^:]*\.py):(?P<line>\d+):\d+:", re.MULTILINE)],
        "test": [
            re.compile(r"^FAILED\s+(?P<file>\S+\.py)(::\S+)?", re.MULTILINE),
            re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+): in ", re.MULTILINE),
        ],
        "security": [
            re.compile(r"Location:\s+(?P<file>\S+\.py):(?P<line>\d+)"),
            re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+):\d+:", re.MULTILINE),
        ],
        "build": [re.compile(r'File "(?P<file>[^"]+\.py)", line (?P<line>\d+)')],
    },
    "javascript": {
        "lint": [re.compile(r"^(?P<file>[^\s].*\.jsx?)$", re.MULTILINE)],
        "format": [re.compile(r"^(?P<file>\S+\.jsx?)$", re.MULTILINE)],
        "test": [re.compile(r"FAIL\s+(?P<file>\S+\.test\.jsx?)")],
        "build": [re.compile(r"in (?P<file>\S+\.jsx?)")],
        "security": [re.compile(r"in\s+(?P<file>\S+\.jsx?)")],
    },
    "typescript": {
        "lint": [re.compile(r"^(?P<file>[^\s].*\.tsx?)$", re.MULTILINE)],
        "format": [re.compile(r"^(?P<file>\S+\.tsx?)$", re.MULTILINE)],
        "test": [re.compile(r"FAIL\s+(?P<file>\S+\.test\.tsx?)")],
        "build": [re.compile(r"^(?P<file>\S+\.tsx?)\((?P<line>\d+),\d+\):", re.MULTILINE)],  # tsc format
        "security": [re.compile(r"in\s+(?P<file>\S+\.tsx?)")],
    },
    "go": {
        "format": [re.compile(r"^(?P<file>\S+\.go)$", re.MULTILINE)],
        "lint": [re.compile(r"^(?P<file>\S+\.go):(?P<line>\d+):\d+:", re.MULTILINE)],
        "build": [re.compile(r"^(?P<file>\S+\.go):(?P<line>\d+):\d+:", re.MULTILINE)],
        "test": [re.compile(r"(?P<file>\S+_test\.go):(?P<line>\d+):")],
        "security": [re.compile(r"^(?P<file>\S+\.go):(?P<line>\d+)", re.MULTILINE)],
    },
}


def _extract_file_and_line(language: str, stage: str, logs: str) -> tuple[Optional[str], Optional[int]]:
    for pattern in EXTRACTION_PATTERNS.get(language, {}).get(stage, []):
        match = pattern.search(logs)
        if match:
            groups = match.groupdict()
            file = groups.get("file")
            line = int(groups["line"]) if groups.get("line") else None
            return file, line
    return None, None


class ValidationPipeline:
    def __init__(self):
        self.executor = SandboxExecutor()

    async def validate(self, repo_dir: Path, language: str = "python") -> Dict:
        """Runs format/lint/build/test/security in sequence for the given
        language, stopping at the first failing stage (no point running
        tests if the build itself is broken)."""
        failures: List[Failure] = []
        for stage in ["format", "lint", "build", "test", "security"]:
            commands = ToolRegistry.get_commands(language, stage)
            if not commands:
                continue
            for command in commands:
                result = await self.executor.run_build(repo_dir, [command])
                if not result["success"]:
                    file, line = _extract_file_and_line(language, stage, result["logs"])
                    failures.append(Failure(
                        stage=stage, command=result["command"], log=result["logs"], file=file, line=line,
                    ))
                    break
            if failures:
                break
        return {"success": len(failures) == 0, "failures": failures}
