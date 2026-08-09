"""
Nakima Sandbox Entrypoint — runs as PID 1 inside the isolated container.

Responsibilities, in strict order:
  1. Clone the target repo at the pinned commit (read-only token, passed via env)
  2. Detect the test suite / language toolchain
  3. Run a baseline full-suite pass BEFORE touching anything — this is the
     control. Without it you can't tell "self-healing fixed it" from
     "the test suite was flaky to begin with."
  4. If trigger == cve_scan: scan dependency manifests against a pre-baked
     CVE database (baked into image at build time — no live network to
     query a live CVE feed, consistent with network_mode=none)
  5. If trigger == synthetic_injection: re-verify consent via the
     SYNTHETIC_INJECTION_CONSENT_VERIFIED env var the orchestrator set
     ONLY after checking repositories.sandbox_lab_opt_in. This is
     defense-in-depth #3 (DB trigger, app-layer check, and now this) —
     redundant checks on a destructive-adjacent action are cheap insurance.
  6. Run the bounded self-healing loop from self_healing.py
  7. Write ONE structured JSON result to /workspace/result.json and exit.
     Never partial-write across multiple files — the orchestrator reads
     exactly one contract, one time, after the container reports done.

This process never pushes, never opens a PR, never touches anything outside
/workspace. Those actions happen later, outside the sandbox, only after a
human approves via the /lab/runs/{id}/review endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/nakima")
from self_healing import (  # noqa: E402
    TestSuiteRunner,
    run_self_healing_loop,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nakima.sandbox.entrypoint")

WORKSPACE = Path("/workspace/repo")
RESULT_PATH = Path("/workspace/result.json")


def write_result(payload: dict) -> None:
    """Single, final write. If this fails, the run is unrecoverable and
    should show up as 'failed' to the orchestrator's TTL/health check —
    silent partial success is worse than a loud failure here."""
    RESULT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("result written to %s", RESULT_PATH)


def clone_repo(clone_url: str, commit_sha: str) -> None:
    WORKSPACE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--no-checkout", clone_url, str(WORKSPACE)], check=True)
    subprocess.run(["git", "checkout", commit_sha], cwd=str(WORKSPACE), check=True)


def detect_test_command(repo_path: Path) -> list[str]:
    """
    Deliberately simple detection, not a plugin system — see Cardinal Rule.
    Extend this list only when a real connected repo needs a stack that
    isn't here yet; don't pre-build support for languages nobody's using.
    """
    if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
        return ["python3", "-m", "pytest", "-q"]
    if (repo_path / "package.json").exists():
        return ["npm", "test", "--silent"]
    raise RuntimeError(
        f"Could not detect a supported test runner in {repo_path}. "
        "This is a known gap — see docs/known-gaps.md. Escalating as failed run "
        "rather than guessing."
    )


def run_baseline(suite_runner: TestSuiteRunner) -> tuple[bool, str]:
    """
    Control run. If the suite is already failing/flaky in a way unrelated
    to the reported CI failure, that's important context to carry forward,
    not to silently absorb into "self-healing fixed it."
    """
    return suite_runner.run()


def scan_dependencies_for_cves(repo_path: Path) -> list[dict]:
    """
    Placeholder for the pre-baked CVE database lookup. Real implementation
    parses requirements.txt / package-lock.json / go.sum etc. against a
    vulnerability DB baked into the image at build time (no live network
    query, per the isolation constraint). Flagged in known-gaps.md — do not
    treat this as a real scan until it's implemented and tested against a
    manifest with a known, confirmed CVE.
    """
    logger.warning("scan_dependencies_for_cves is a placeholder — see known-gaps.md")
    return []


def maybe_inject_synthetic_vulnerability(repo_path: Path) -> bool:
    consent_verified = os.environ.get("SYNTHETIC_INJECTION_CONSENT_VERIFIED") == "true"
    if not consent_verified:
        logger.info("synthetic injection not requested or consent not verified — skipping")
        return False
    # TODO(known-gap): real injection logic. Must operate on this sandbox's
    # ephemeral clone only (already guaranteed — this whole container is the
    # ephemeral clone) and must be logged with exactly what was injected, so
    # the "fix" produced downstream can be checked against a known-good answer.
    logger.warning("synthetic injection requested but not yet implemented — see known-gaps.md")
    return False


def pattern_lookup_stub(vulnerability_class: str, language: str) -> list[dict]:
    """
    Read-only lookup against pattern_memory. In the isolated sandbox
    (network_mode=none) this cannot be a live DB call — the orchestrator
    must inject a pre-fetched, relevant snapshot of pattern_memory rows
    into the container at launch time (e.g. as a mounted read-only tmpfs
    file), not open a network path out for this lookup either. Keeping this
    stub explicit so nobody accidentally adds a live DB connection here later
    and quietly breaks the isolation guarantee.
    """
    return []


def main() -> None:
    run_id = os.environ["RUN_ID"]
    clone_url = os.environ["REPO_CLONE_URL"]
    commit_sha = os.environ["COMMIT_SHA"]
    trigger = os.environ.get("TRIGGER", "manual")

    started_at = time.time()
    logger.info("sandbox run %s starting, trigger=%s", run_id, trigger)

    try:
        clone_repo(clone_url, commit_sha)
        test_command = detect_test_command(WORKSPACE)
        suite_runner = TestSuiteRunner(run_command=test_command, cwd=str(WORKSPACE))

        baseline_passed, baseline_output = run_baseline(suite_runner)

        cve_findings = scan_dependencies_for_cves(WORKSPACE) if trigger == "cve_scan" else []
        injected = maybe_inject_synthetic_vulnerability(WORKSPACE) if trigger == "synthetic_injection" else False

        if baseline_passed and not cve_findings and not injected:
            write_result(
                {
                    "run_id": run_id,
                    "status": "no_issue_found",
                    "baseline_passed": True,
                    "duration_seconds": round(time.time() - started_at, 1),
                }
            )
            return

        # This is the ci_log input to the healing loop — for a CI-triggered
        # run this would be the actual GitHub Actions log fetched by the
        # orchestrator and passed in; for cve_scan/synthetic triggers it's
        # the baseline failure output plus findings, framed the same way so
        # the healing loop has one consistent input shape regardless of
        # trigger type.
        ci_log = baseline_output if not baseline_passed else json.dumps(cve_findings)

        heal_result = run_self_healing_loop(
            ci_log=ci_log,
            repo_context={"primary_language": _guess_primary_language(WORKSPACE)},
            repo_snapshot_path=str(WORKSPACE),
            suite_runner=suite_runner,
            pattern_lookup_fn=pattern_lookup_stub,
        )

        write_result(
            {
                "run_id": run_id,
                "status": "healed" if heal_result.success else "escalated",
                "baseline_passed": baseline_passed,
                "attempts_used": heal_result.attempts_used,
                "confidence_score": heal_result.confidence_score,
                "requires_mandatory_review": heal_result.requires_mandatory_review,
                "escalation_reason": heal_result.escalation_reason,
                "selected_diff": heal_result.selected_candidate.diff if heal_result.selected_candidate else None,
                "diagnosis": {
                    "failure_class": heal_result.final_diagnosis.failure_class.value
                    if heal_result.final_diagnosis
                    else "unknown",
                    "root_cause_summary": heal_result.final_diagnosis.root_cause_summary
                    if heal_result.final_diagnosis
                    else None,
                    "is_security_relevant": heal_result.final_diagnosis.is_security_relevant
                    if heal_result.final_diagnosis
                    else False,
                },
                "candidate_count": len(heal_result.all_candidates),
                "duration_seconds": round(time.time() - started_at, 1),
            }
        )

    except Exception as exc:  # noqa: BLE001 — top-level entrypoint must never crash without a result file
        logger.exception("sandbox run %s failed", run_id)
        write_result(
            {
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
                "duration_seconds": round(time.time() - started_at, 1),
            }
        )
        sys.exit(1)


def _guess_primary_language(repo_path: Path) -> str:
    if (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists():
        return "python"
    if (repo_path / "package.json").exists():
        return "javascript"
    return "unknown"


if __name__ == "__main__":
    main()
