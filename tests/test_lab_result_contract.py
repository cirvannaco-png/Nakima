import uuid

import pytest
from pydantic import ValidationError

from lab.result_contract import LabRunResult


def test_no_issue_found_requires_passing_full_baseline():
    with pytest.raises(ValidationError, match="passing full baseline"):
        LabRunResult(
            run_id=uuid.uuid4(),
            commit_sha="a" * 40,
            status="no_issue_found",
            baseline_passed=True,
            full_test_suite_passed=False,
            duration_seconds=1.0,
        )


def test_healed_requires_selected_diff_and_full_suite_evidence():
    with pytest.raises(ValidationError, match="selected diff"):
        LabRunResult(
            run_id=uuid.uuid4(),
            commit_sha="b" * 40,
            status="healed",
            baseline_passed=False,
            full_test_suite_passed=False,
            duration_seconds=1.0,
        )


def test_failed_result_requires_error_code_and_message():
    with pytest.raises(ValidationError, match="error code"):
        LabRunResult(
            run_id=uuid.uuid4(),
            commit_sha="c" * 40,
            status="failed",
            duration_seconds=0.5,
        )


def test_escalated_result_must_require_human_review():
    with pytest.raises(ValidationError, match="human review"):
        LabRunResult(
            run_id=uuid.uuid4(),
            commit_sha="d" * 40,
            status="escalated",
            baseline_passed=False,
            requires_mandatory_review=False,
            duration_seconds=1.0,
        )
