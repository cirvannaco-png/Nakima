"""Tests for quality/gate.py."""

from quality.gate import QualityGate, QualityVerdict


def test_no_files_changed_approves():
    result = QualityGate().evaluate([])
    assert result.verdict == QualityVerdict.APPROVE


def test_docs_only_change_approves_without_tests():
    result = QualityGate().evaluate(["README.md", "docs/guide.md"])
    assert result.verdict == QualityVerdict.APPROVE
    assert result.has_test_changes is False


def test_source_change_with_matching_test_dir_approves():
    result = QualityGate().evaluate(["security/nsil.py", "tests/test_security_nsil.py"])
    assert result.verdict == QualityVerdict.APPROVE
    assert result.has_test_changes is True


def test_source_change_with_test_prefixed_file_approves():
    result = QualityGate().evaluate(["quality/gate.py", "test_quality_gate.py"])
    assert result.verdict == QualityVerdict.APPROVE


def test_source_change_with_test_suffixed_file_approves():
    result = QualityGate().evaluate(["quality/gate.py", "quality/gate_test.py"])
    assert result.verdict == QualityVerdict.APPROVE


def test_source_change_with_no_tests_warns():
    result = QualityGate().evaluate(["quality/gate.py", "orchestrator/workflow.py"])
    assert result.verdict == QualityVerdict.WARN
    assert result.has_test_changes is False
    assert "no test file touched" in result.reasoning[0]


def test_migration_file_counts_as_source_and_warns_without_a_test():
    result = QualityGate().evaluate(["requirements.txt", "alembic/versions/0007_x.py"])
    # alembic migrations end in .py so they DO count as source here —
    # this asserts the actual (honest) behavior rather than assuming a
    # migration-specific carve-out that doesn't exist in the code.
    assert result.verdict == QualityVerdict.WARN


def test_never_blocks_only_warns_or_approves():
    for files in ([], ["a.py"], ["a.py", "tests/test_a.py"], ["a.md"]):
        result = QualityGate().evaluate(files)
        assert result.verdict in (QualityVerdict.APPROVE, QualityVerdict.WARN)
