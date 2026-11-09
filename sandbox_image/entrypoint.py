"""Isolated Lab entrypoint.

The trusted host mounts one pinned source archive read-only and passes its
SHA-256 digest. This process has no repository credential, clone URL, network,
database URL, or Docker socket. Repository test commands are demoted to UID
10001; only this controller writes the root-owned result mount.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from lab.result_contract import LabDiagnosis, LabRunResult
from lab.source_bundle import PinnedSourceBundle, extract_verified_source_bundle
from self_healing import TestSuiteRunner, run_self_healing_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nakima.lab.entrypoint")

ARCHIVE_PATH = Path("/input/source.tar.gz")
WORKSPACE = Path("/workspace/repo")
RESULT_PATH = Path("/output/result.json")
UNTRUSTED_UID = 10001
UNTRUSTED_GID = 10001
COMMIT_SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ALLOWED_TRIGGERS = {"ci_failure", "cve_scan", "synthetic_injection", "manual"}
FORBIDDEN_ENV_KEYS = {
    "GITHUB_TOKEN",
    "GITHUB_PRIVATE_KEY",
    "GITHUB_APP_PRIVATE_KEY",
    "DATABASE_URL",
    "REPO_CLONE_URL",
    "GIT_ASKPASS",
}


def write_result(result: LabRunResult) -> None:
    """Atomically write one validated result to the root-owned output mount."""
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = RESULT_PATH.with_suffix(".json.tmp")
    payload = result.model_dump_json(indent=2)
    descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, RESULT_PATH)
        os.chmod(RESULT_PATH, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)
    logger.info("validated result written")


def _validate_environment() -> tuple[uuid.UUID, str, str, str]:
    run_id = uuid.UUID(os.environ["RUN_ID"])
    commit_sha = os.environ["COMMIT_SHA"]
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise ValueError("COMMIT_SHA must be a full immutable 40- or 64-character SHA")
    if os.environ.get("SOURCE_ARCHIVE_PATH") != str(ARCHIVE_PATH):
        raise ValueError("SOURCE_ARCHIVE_PATH must be the trusted read-only archive mount")
    archive_sha256 = os.environ["SOURCE_ARCHIVE_SHA256"]
    if not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        raise ValueError("SOURCE_ARCHIVE_SHA256 must be a lowercase SHA-256 digest")
    trigger = os.environ.get("TRIGGER", "manual")
    if trigger not in ALLOWED_TRIGGERS:
        raise ValueError("Unsupported Lab trigger")

    unexpected_credentials = sorted(key for key in FORBIDDEN_ENV_KEYS if os.environ.get(key))
    if unexpected_credentials:
        raise ValueError(
            "Forbidden credential or clone environment present: " + ", ".join(unexpected_credentials)
        )
    return run_id, commit_sha, archive_sha256, trigger


def _demote_workspace_to_untrusted_user(workspace: Path) -> None:
    """Make the extracted repository writable only by the unprivileged test UID."""
    for item in workspace.rglob("*"):
        if item.is_symlink():
            raise RuntimeError("Source archive extraction unexpectedly produced a symlink")
        os.chown(item, UNTRUSTED_UID, UNTRUSTED_GID)
    os.chown(workspace, UNTRUSTED_UID, UNTRUSTED_GID)


def _extract_pinned_source(commit_sha: str, archive_sha256: str) -> None:
    if not ARCHIVE_PATH.is_file():
        raise RuntimeError("Pinned source archive is not mounted")
    archive_size = ARCHIVE_PATH.stat().st_size
    bundle = PinnedSourceBundle(
        repository_full_name=os.environ.get("REPOSITORY_FULL_NAME", "archive-only"),
        commit_sha=commit_sha,
        archive_path=ARCHIVE_PATH,
        archive_sha256=archive_sha256,
        archive_size_bytes=archive_size,
    )
    extract_verified_source_bundle(bundle, WORKSPACE)
    _demote_workspace_to_untrusted_user(WORKSPACE)


def detect_test_command(repo_path: Path) -> list[str]:
    """Small supported matrix; unknown stacks fail instead of guessing."""
    if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
        return ["python3", "-m", "pytest", "-q"]
    if (repo_path / "package.json").exists():
        raise RuntimeError(
            "Node.js repositories are not supported until a verified offline dependency cache is available"
        )
    raise RuntimeError("No supported test runner was detected in the pinned repository")


def _failed_result(
    run_id: uuid.UUID,
    commit_sha: str,
    started_at: float,
    error_code: str,
    error: str,
    *,
    baseline_passed: bool | None = None,
    full_test_suite_passed: bool | None = None,
) -> LabRunResult:
    return LabRunResult(
        run_id=run_id,
        commit_sha=commit_sha,
        status="failed",
        baseline_passed=baseline_passed,
        full_test_suite_passed=full_test_suite_passed,
        requires_mandatory_review=True,
        error_code=error_code[:128],
        error=error[:4000],
        duration_seconds=max(0.0, time.time() - started_at),
    )


def main() -> int:
    # Run ID and commit SHA are trusted-host inputs needed to bind every result
    # to the request. If they are invalid, no result can safely be attributed.
    run_id = uuid.UUID(os.environ["RUN_ID"])
    commit_sha = os.environ["COMMIT_SHA"]
    if not COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise SystemExit("Invalid immutable commit SHA")

    started_at = time.time()
    try:
        run_id, commit_sha, archive_sha256, trigger = _validate_environment()
        logger.info("Lab run %s starting, trigger=%s, commit=%s", run_id, trigger, commit_sha)

        _extract_pinned_source(commit_sha, archive_sha256)
        test_command = detect_test_command(WORKSPACE)
        suite_runner = TestSuiteRunner(
            run_command=test_command,
            cwd=str(WORKSPACE),
            run_as_uid=UNTRUSTED_UID,
            run_as_gid=UNTRUSTED_GID,
        )

        baseline_passed, baseline_output = suite_runner.run()

        # These trigger types are deliberately unavailable until their
        # implementations are proven against known fixtures. Do not report a
        # clean scan or a completed injection from placeholder code.
        if trigger == "cve_scan":
            result = _failed_result(
                run_id,
                commit_sha,
                started_at,
                "cve_scanner_not_implemented",
                "Offline vulnerability-database scanning is not implemented",
                baseline_passed=baseline_passed,
                full_test_suite_passed=baseline_passed,
            )
            write_result(result)
            return 1

        if trigger == "synthetic_injection":
            if os.environ.get("SYNTHETIC_INJECTION_CONSENT_VERIFIED") != "true":
                raise PermissionError("Synthetic injection consent was not verified by the trusted host")
            result = _failed_result(
                run_id,
                commit_sha,
                started_at,
                "synthetic_injection_not_implemented",
                "Synthetic vulnerability injection is not implemented",
                baseline_passed=baseline_passed,
                full_test_suite_passed=baseline_passed,
            )
            write_result(result)
            return 1

        if trigger == "ci_failure" and baseline_passed:
            # The original provider CI log is not yet transferred as a
            # separately verified artifact. A passing local baseline cannot
            # be reported as a fix for an external CI failure.
            result = LabRunResult(
                run_id=run_id,
                commit_sha=commit_sha,
                status="escalated",
                baseline_passed=True,
                full_test_suite_passed=True,
                requires_mandatory_review=True,
                error_code="ci_failure_not_reproduced",
                error="The pinned commit passed its local baseline; source CI evidence was not supplied",
                duration_seconds=max(0.0, time.time() - started_at),
            )
            write_result(result)
            return 0

        if baseline_passed and trigger == "manual":
            result = LabRunResult(
                run_id=run_id,
                commit_sha=commit_sha,
                status="no_issue_found",
                baseline_passed=True,
                full_test_suite_passed=True,
                requires_mandatory_review=False,
                duration_seconds=max(0.0, time.time() - started_at),
            )
            write_result(result)
            return 0

        heal_result = run_self_healing_loop(
            ci_log=baseline_output,
            repo_context={"primary_language": _guess_primary_language(WORKSPACE)},
            repo_snapshot_path=str(WORKSPACE),
            suite_runner=suite_runner,
            pattern_lookup_fn=lambda _failure_class, _language: [],
        )
        diagnosis = None
        if heal_result.final_diagnosis is not None:
            diagnosis = LabDiagnosis(
                failure_class=heal_result.final_diagnosis.failure_class.value,
                root_cause_summary=heal_result.final_diagnosis.root_cause_summary or "No summary provided",
                affected_files=heal_result.final_diagnosis.affected_files or [],
                is_security_relevant=heal_result.final_diagnosis.is_security_relevant,
            )
        selected = heal_result.selected_candidate
        selected_passed = bool(selected and selected.full_suite_passed and selected.diff)
        healed = bool(heal_result.success and selected_passed)
        result = LabRunResult(
            run_id=run_id,
            commit_sha=commit_sha,
            status="healed" if healed else "escalated",
            baseline_passed=baseline_passed,
            full_test_suite_passed=selected_passed,
            attempts_used=heal_result.attempts_used,
            confidence_score=heal_result.confidence_score,
            requires_mandatory_review=True,
            diagnosis=diagnosis,
            selected_diff=selected.diff if healed else None,
            candidate_count=len(heal_result.all_candidates),
            error_code=None if healed else "no_validated_candidate",
            error=None if healed else (heal_result.escalation_reason or "No candidate passed full-suite validation"),
            duration_seconds=max(0.0, time.time() - started_at),
        )
        write_result(result)
        return 0

    except Exception as exc:  # noqa: BLE001 — always emit a terminal, typed failure when possible
        logger.exception("Lab run %s failed", run_id)
        result = _failed_result(
            run_id,
            commit_sha,
            started_at,
            type(exc).__name__,
            str(exc),
        )
        write_result(result)
        return 1


def _guess_primary_language(repo_path: Path) -> str:
    if (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists():
        return "python"
    if (repo_path / "package.json").exists():
        return "javascript"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
