"""Builds a ProjectRealityModel snapshot: what a repository actually
contains right now, measured, not asserted. Reuses repository.analysis
(tree-sitter symbol extraction) and repository.health (the existing
radon-based scorer) instead of re-implementing either — this module's only
new logic is language/LOC/test-file counting and dependency-manifest
parsing.
"""

import json
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from models.neis.project_reality import ProjectRealityModel
from repository.analysis import LANG_BY_EXT
from repository.health import HealthScorer

# Directories that are never "the project" — build output, vendored deps,
# VCS internals. Walking these would make LOC/dependency counts reflect
# whatever's installed locally rather than what's committed.
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".mypy_cache",
}

# Same naming heuristic repository.health.HealthScorer already uses for its
# test-to-code ratio — kept consistent rather than inventing a second rule
# for "is this a test file".
TEST_FILE_PATTERN = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|tests?/.+\.(py|js|ts|jsx|tsx))$")


class ProjectModeler:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def build_snapshot(self, repo_dir: Path, repository_id: int) -> ProjectRealityModel:
        repo_dir = Path(repo_dir)
        all_files = [
            f for f in repo_dir.rglob("*") if f.is_file() and not any(part in IGNORED_DIRS for part in f.parts)
        ]

        languages, loc_by_language = self._language_and_loc_counts(all_files)
        test_file_count = sum(
            1 for f in all_files if TEST_FILE_PATTERN.search(str(f.relative_to(repo_dir)).replace("\\", "/"))
        )
        dependencies = self._collect_dependencies(repo_dir)

        health = await HealthScorer(repo_dir).score() if languages.get("python") else {"score": None}

        snapshot = ProjectRealityModel(
            repository_id=repository_id,
            languages=languages,
            dependencies=dependencies,
            loc_by_language=loc_by_language,
            file_count=len(all_files),
            test_file_count=test_file_count,
            health_score=health.get("score"),
            health_components=health.get("components"),
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    def _language_and_loc_counts(self, all_files: list[Path]) -> tuple[dict, dict]:
        languages: dict[str, int] = {}
        loc: dict[str, int] = {}
        for f in all_files:
            lang = LANG_BY_EXT.get(f.suffix)
            if not lang:
                continue
            languages[lang] = languages.get(lang, 0) + 1
            try:
                lines = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            loc[lang] = loc.get(lang, 0) + lines
        return languages, loc

    def _collect_dependencies(self, repo_dir: Path) -> list[dict]:
        deps: list[dict] = []
        deps.extend(self._parse_requirements_txt(repo_dir / "requirements.txt"))
        deps.extend(self._parse_package_json(repo_dir / "package.json"))
        return deps

    def _parse_requirements_txt(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        deps = []
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            match = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*==\s*([A-Za-z0-9_.\-]+)", line)
            if match:
                name = match.group(1).split("[")[0]  # strip extras, e.g. "uvicorn[standard]"
                deps.append({"name": name, "version": match.group(2), "ecosystem": "pypi"})
        return deps

    def _parse_package_json(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        deps = []
        for section in ("dependencies", "devDependencies"):
            for name, version in data.get(section, {}).items():
                deps.append({"name": name, "version": str(version).lstrip("^~"), "ecosystem": "npm"})
        return deps
