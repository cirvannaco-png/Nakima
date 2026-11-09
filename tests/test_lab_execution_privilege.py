from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from orchestrator.self_healing import TestSuiteRunner


def test_repository_test_command_runs_as_unprivileged_uid_and_gid():
    completed = CompletedProcess(
        args=["python3", "-m", "pytest"],
        returncode=0,
        stdout="passed",
        stderr="",
    )
    with patch("orchestrator.self_healing.subprocess.run", return_value=completed) as run:
        suite = TestSuiteRunner(
            run_command=["python3", "-m", "pytest"],
            cwd="/workspace/repo",
            run_as_uid=10001,
            run_as_gid=10001,
        )
        passed, output = suite.run()

    assert passed is True
    assert "passed" in output
    assert run.call_args.kwargs["user"] == 10001
    assert run.call_args.kwargs["group"] == 10001
    assert run.call_args.kwargs["extra_groups"] == []


def test_test_suite_runner_requires_both_uid_and_gid():
    suite = TestSuiteRunner(
        run_command=["python3", "-m", "pytest"],
        cwd="/workspace/repo",
        run_as_uid=10001,
    )

    with pytest.raises(ValueError, match="Both run_as_uid and run_as_gid"):
        suite.run()
