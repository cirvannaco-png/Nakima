"""
Nakima Lab — Sandbox Orchestrator
==================================

Design stance (per Cardinal Rule): single-process FastAPI service, no
Kubernetes, no message queue beyond Postgres-backed job state. Isolation is
achieved via ephemeral Docker containers with no network access to
production infra — this is a SECURITY requirement, not a scale one, so it
does not trip the "unjustified complexity" check. If/when concurrent sandbox
runs exceed what one host can schedule, the justified next step is a job
queue (e.g. a `jobs` table polled by workers, NOT Kafka) — not before.

Flow enforced by this service:
  1. Clone target repo read-only into an ephemeral container (network: none)
  2. Run CVE scan / synthetic injection (only if repo opted in) / self-heal loop
  3. Persist diagnosis + proposed diff to sandbox_runs (tenant-isolated table)
  4. Never touch the live repo. Never auto-merge. Never auto-push.
  5. On container exit (success, failure, or TTL expiry) — destroy it. No
     container outlives its run. No state persists in the container itself;
     everything durable goes to Postgres.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import docker
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger("nakima.lab.orchestrator")

app = FastAPI(title="Nakima Lab Orchestrator", version="0.1.0")
docker_client = docker.from_env()

SANDBOX_IMAGE = "nakima-sandbox-runner:latest"
CONTAINER_TTL_SECONDS = 60 * 60 * 2  # hard ceiling; runs must finish or die within 2h
MAX_CONCURRENT_RUNS = 4  # matches a single-host budget; revisit only with real concurrency data


class RunTrigger(str, Enum):
    ci_failure = "ci_failure"
    cve_scan = "cve_scan"
    synthetic_injection = "synthetic_injection"
    manual = "manual"


class SandboxRunRequest(BaseModel):
    organization_id: uuid.UUID
    repository_id: uuid.UUID
    source_commit_sha: str
    trigger: RunTrigger
    request_synthetic_injection: bool = False


class SandboxRunHandle(BaseModel):
    run_id: uuid.UUID
    status: str
    container_id: Optional[str] = None


# In production this is a DB-backed table (sandbox_runs); kept as an
# in-memory stub here so the orchestrator logic is reviewable standalone.
_ACTIVE_RUNS: dict[str, dict] = {}


async def _repo_has_lab_consent(repository_id: uuid.UUID) -> bool:
    """
    Must check `repositories.sandbox_lab_opt_in` before permitting synthetic
    vulnerability injection. This mirrors the DB trigger in schema.sql as a
    defense-in-depth check at the application layer — the DB constraint is
    the real enforcement point, this is the fast-fail.
    """
    # TODO: replace with real DB call
    raise NotImplementedError("wire to repositories table")


def _launch_isolated_container(
    run_id: str, repo_clone_url: str, commit_sha: str, trigger: str, synthetic_injection_verified: bool
) -> str:
    """
    Launches a fully network-isolated container to run the sandbox.

    Isolation guarantees enforced here:
      - network_mode="none": no egress, no ingress, cannot reach prod infra,
        cannot reach the public internet either (dependency mirrors must be
        pre-baked into the sandbox image, not fetched at runtime)
      - read_only root filesystem except a scoped /workspace tmpfs
      - no volume mounts to host paths that touch live deploy credentials
      - resource limits to prevent one run from starving the host
    """
    container = docker_client.containers.run(
        image=SANDBOX_IMAGE,
        name=f"nakima-sandbox-{run_id}",
        detach=True,
        network_mode="none",
        read_only=True,
        tmpfs={"/workspace": "size=2g,exec"},
        mem_limit="2g",
        nano_cpus=2_000_000_000,  # 2 CPUs
        environment={
            "REPO_CLONE_URL": repo_clone_url,
            "COMMIT_SHA": commit_sha,
            "RUN_ID": run_id,
            "TRIGGER": trigger,
            # Set to "true" ONLY after this process has independently verified
            # repositories.sandbox_lab_opt_in == true — see _repo_has_lab_consent.
            # This is defense-in-depth layer #2 (DB trigger in schema.sql is #1,
            # entrypoint.py's own re-check is #3). Never set this based on the
            # request payload alone.
            "SYNTHETIC_INJECTION_CONSENT_VERIFIED": "true" if synthetic_injection_verified else "false",
        },
        labels={
            "nakima.run_id": run_id,
            "nakima.component": "sandbox",
            "nakima.ttl_seconds": str(CONTAINER_TTL_SECONDS),
        },
        auto_remove=False,  # we remove explicitly after log/result capture
    )
    return container.id


@app.post("/lab/runs", response_model=SandboxRunHandle, status_code=202)
async def create_sandbox_run(req: SandboxRunRequest, background_tasks: BackgroundTasks):
    if req.request_synthetic_injection:
        if req.trigger != RunTrigger.synthetic_injection:
            raise HTTPException(400, "request_synthetic_injection requires trigger='synthetic_injection'")
        allowed = await _repo_has_lab_consent(req.repository_id)
        if not allowed:
            raise HTTPException(
                403,
                "This repository has not opted into synthetic vulnerability injection. "
                "Enable it explicitly in repo settings before requesting this run type.",
            )

    running = sum(1 for r in _ACTIVE_RUNS.values() if r["status"] in ("provisioning", "running"))
    if running >= MAX_CONCURRENT_RUNS:
        raise HTTPException(429, f"At capacity ({MAX_CONCURRENT_RUNS} concurrent sandbox runs). Try again shortly.")

    run_id = str(uuid.uuid4())
    _ACTIVE_RUNS[run_id] = {
        "status": "provisioning",
        "organization_id": str(req.organization_id),
        "repository_id": str(req.repository_id),
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=CONTAINER_TTL_SECONDS),
    }

    background_tasks.add_task(_run_sandbox_lifecycle, run_id, req)
    return SandboxRunHandle(run_id=uuid.UUID(run_id), status="provisioning")


async def _run_sandbox_lifecycle(run_id: str, req: SandboxRunRequest):
    """
    Full lifecycle: provision -> run -> capture result -> destroy container.
    Always destroys the container in a finally block — no orphaned sandboxes,
    even on crash.
    """
    try:
        clone_url = await _resolve_clone_url(req.repository_id)  # read-only deploy key scoped to this repo only

        # Re-verify consent here too, independent of the check in
        # create_sandbox_run — this is the request-handling process's own
        # defense-in-depth layer, not a reuse of the earlier check's result.
        synthetic_verified = (
            req.request_synthetic_injection and await _repo_has_lab_consent(req.repository_id)
        )

        container_id = await asyncio.to_thread(
            _launch_isolated_container,
            run_id, clone_url, req.source_commit_sha, req.trigger.value, synthetic_verified,
        )
        _ACTIVE_RUNS[run_id]["container_id"] = container_id
        _ACTIVE_RUNS[run_id]["status"] = "running"

        result = await _await_container_completion(container_id, timeout=CONTAINER_TTL_SECONDS)

        _ACTIVE_RUNS[run_id]["status"] = "awaiting_review"
        await _persist_run_result(run_id, req, result)

    except asyncio.TimeoutError:
        logger.warning("sandbox run %s exceeded TTL, forcing teardown", run_id)
        _ACTIVE_RUNS[run_id]["status"] = "expired"
    except Exception:
        logger.exception("sandbox run %s failed", run_id)
        _ACTIVE_RUNS[run_id]["status"] = "failed"
    finally:
        await _destroy_container_if_exists(run_id)


async def _resolve_clone_url(repository_id: uuid.UUID) -> str:
    # TODO: fetch a read-only, repo-scoped GitHub App installation token —
    # never the org's general PAT, never write-scoped.
    raise NotImplementedError


async def _await_container_completion(container_id: str, timeout: int) -> dict:
    # TODO: poll container status / stream logs; parse structured JSON result
    # written by the sandbox entrypoint to a known path before it exits.
    raise NotImplementedError


async def _persist_run_result(run_id: str, req: SandboxRunRequest, result: dict):
    """
    Writes diagnosis + proposed_fix_diff to `sandbox_runs`. Does NOT write
    anything to `pattern_memory` here — that promotion is a separate,
    deliberate, offline/batch step reviewed by a human (see
    docs/NEIS_LEARNING_POLICY.md). No live weight updates happen in this path.
    """
    # TODO: DB write
    raise NotImplementedError


async def _destroy_container_if_exists(run_id: str):
    container_id = _ACTIVE_RUNS.get(run_id, {}).get("container_id")
    if not container_id:
        return
    try:
        container = docker_client.containers.get(container_id)
        container.remove(force=True)
    except docker.errors.NotFound:
        pass


@app.get("/lab/runs/{run_id}", response_model=SandboxRunHandle)
async def get_sandbox_run(run_id: uuid.UUID):
    run = _ACTIVE_RUNS.get(str(run_id))
    if not run:
        raise HTTPException(404, "run not found")
    return SandboxRunHandle(run_id=run_id, status=run["status"], container_id=run.get("container_id"))


@app.post("/lab/runs/{run_id}/review")
async def review_sandbox_run(run_id: uuid.UUID, decision: str, reviewer_user_id: uuid.UUID, notes: str = ""):
    """
    Human approval gate. Only 'approved' runs are eligible for PR creation —
    and PR creation is a SEPARATE call the user must also explicitly trigger
    from the dashboard, not an automatic consequence of approval. Two
    deliberate clicks between "sandbox found a fix" and "code changes on
    the real repo," by design.
    """
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")
    run = _ACTIVE_RUNS.get(str(run_id))
    if not run:
        raise HTTPException(404, "run not found")
    if run["status"] != "awaiting_review":
        raise HTTPException(409, f"run is in status '{run['status']}', not awaiting review")
    run["status"] = decision
    # TODO: persist to run_reviews table
    return {"run_id": run_id, "status": decision}
