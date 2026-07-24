"""The Quality Gate. Deliberately scoped to one honest, deterministic
check rather than a broad "is this good code" judgment call — that
broader question belongs to CognitiveEngine (neis/reasoning/), not here.

What this does NOT do, on purpose: map a changed source file to "the"
test file that should cover it and check it was touched. This repo's own
test suite doesn't follow a rigid 1:1 naming convention (compare
neis/reasoning/decision_engine.py, covered by tests/test_reasoning.py,
against security/nsil.py, covered by tests/test_security_nsil.py — no
mechanical rule predicts either name from the source path). A gate built
on a naming convention the codebase doesn't actually follow would produce
constant false positives and would itself be a form of the "supplying
unstated assumptions to make something look more rigorous than it is"
mistake. What IS checkable without guessing: whether *any* test file was
touched at all when non-test source files were also touched. That's a
weaker signal — it doesn't prove adequate coverage — but it's true rather
than merely plausible-looking, which matters more.
"""

import enum
from dataclasses import dataclass, field
from pathlib import PurePosixPath


class QualityVerdict(str, enum.Enum):
    APPROVE = "approve"
    WARN = "warn"


@dataclass
class QualityGateResult:
    verdict: QualityVerdict
    reasoning: list[str] = field(default_factory=list)
    has_test_changes: bool = False


def _is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    return "tests" in p.parts or p.stem.startswith("test_") or p.stem.endswith("_test")


def _is_source_file(path: str) -> bool:
    """Files where "this probably needed a test" is a reasonable prior —
    excludes docs, config, migrations (which have their own review
    posture) and lockfiles.
    """
    p = PurePosixPath(path)
    if _is_test_file(path):
        return False
    return p.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go"}


class QualityGate:
    def evaluate(self, changed_files: list[str]) -> QualityGateResult:
        test_files = [f for f in changed_files if _is_test_file(f)]
        source_files = [f for f in changed_files if _is_source_file(f)]
        has_test_changes = bool(test_files)

        if not source_files:
            return QualityGateResult(
                verdict=QualityVerdict.APPROVE,
                reasoning=["No source files changed — nothing for a test-coverage signal to apply to."],
                has_test_changes=has_test_changes,
            )

        if has_test_changes:
            return QualityGateResult(
                verdict=QualityVerdict.APPROVE,
                reasoning=[f"{len(test_files)} test file(s) touched alongside {len(source_files)} source file(s)."],
                has_test_changes=True,
            )

        return QualityGateResult(
            verdict=QualityVerdict.WARN,
            reasoning=[
                f"{len(source_files)} source file(s) changed with no test file touched. This doesn't "
                "block — some changes genuinely don't need new tests (config, docs-adjacent code, "
                "pure refactors already covered by existing tests) — but it's worth a human's attention "
                "before merge."
            ],
            has_test_changes=False,
        )
