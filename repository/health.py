from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import mi_visit

from security.policy_checker import PolicyChecker


class HealthScorer:
    """Produces a 0-100 repository health score from static metrics. This
    is deliberately cheap (no sandbox, no AI calls) so it can run on every
    push without adding latency to the main pipeline."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)

    async def score(self) -> dict:
        py_files = list(self.repo_dir.rglob("*.py"))
        if not py_files:
            return {"score": None, "reason": "no Python files found"}

        complexity = self._average_complexity(py_files)
        maintainability = self._average_maintainability(py_files)
        test_ratio = self._test_to_code_ratio(py_files)
        docstring_coverage = self._docstring_coverage(py_files)

        # Weighted blend, each normalized to 0-100 first.
        complexity_score = max(0, 100 - (complexity - 1) * 10) if complexity is not None else 50
        test_score = min(test_ratio * 200, 100)  # 0.5 files-of-tests-per-file-of-code == 100
        docstring_score = docstring_coverage * 100

        overall = round(
            complexity_score * 0.35 + (maintainability or 50) * 0.25 + test_score * 0.25 + docstring_score * 0.15, 1
        )

        return {
            "score": overall,
            "components": {
                "avg_cyclomatic_complexity": complexity,
                "avg_maintainability_index": maintainability,
                "test_to_code_file_ratio": round(test_ratio, 3),
                "docstring_coverage": round(docstring_coverage, 3),
            },
        }

    def _average_complexity(self, py_files: list) -> float | None:
        scores = []
        for f in py_files:
            try:
                blocks = cc_visit(f.read_text())
                scores.extend(b.complexity for b in blocks)
            except Exception:
                continue
        return round(sum(scores) / len(scores), 2) if scores else None

    def _average_maintainability(self, py_files: list) -> float | None:
        scores = []
        for f in py_files:
            try:
                scores.append(mi_visit(f.read_text(), multi=True))
            except Exception:
                continue
        return round(sum(scores) / len(scores), 2) if scores else None

    def _test_to_code_ratio(self, py_files: list) -> float:
        test_files = [f for f in py_files if f.name.startswith("test_") or f.name.endswith("_test.py")]
        code_files = [f for f in py_files if f not in test_files]
        if not code_files:
            return 0.0
        return len(test_files) / len(code_files)

    def _docstring_coverage(self, py_files: list) -> float:
        checker = PolicyChecker.__new__(PolicyChecker)  # pure function, no DB needed here
        total_symbols = 0
        missing = 0
        for f in py_files:
            found_missing = checker._missing_docstrings(f)
            missing += len(found_missing)
            # _missing_docstrings only returns names, so estimate a denominator
            # by re-parsing symbol count via the same file (best-effort).
            try:
                import ast

                tree = ast.parse(f.read_text())
                total_symbols += sum(
                    1
                    for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                    and not n.name.startswith("_")
                )
            except Exception:
                continue
        if total_symbols == 0:
            return 1.0
        return max(0.0, 1 - (missing / total_symbols))
