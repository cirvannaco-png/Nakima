"""Nakima Lab API.

This service is deliberately not mounted by the production app. The API
requires OIDC authentication and installation-scoped authorization. Execution
remains disabled until the host-side clone, immutable archive transfer,
network-isolated runner, result contract, and durable lifecycle are complete.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from lab.auth import LabPrincipal, get_current_lab_principal
from lab.authorization import (
    READ_ROLES,
    REVIEW_ROLES,
    RUN_ROLES,
    grant_installation_membership,
    is_lab_operator,
    require_installation_role,
    revoke_installation_membership,
)
from models.lab import RunReview, SandboxRun
from models.provider_installation import ProviderInstallation
from models.provider_installation_membership import ProviderInstallationMembership
from models.repository import Repository

app = FastAPI(title="Nakima Lab Orchestrator", version="0.2.0")


class RunTrigger(StrEnum):
    ci_failure = "ci_failure"
    cve_scan = "cve_scan"
    synthetic_injection = "synthetic_injection"
    manual = "manual"


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Use Nakima's canonical integer repository key. The former caller-
    # supplied UUID repository/organization pair belonged to the abandoned
    # second schema and could not be resolved against the application DB.
    repository_id: int = Field(gt=0)
    source_commit_sha: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    trigger: RunTrigger
    request_synthetic_injection: bool = False

    @model_validator(mode="after")
    def validate_synthetic_request(self):
        is_synthetic = self.trigger == RunTrigger.synthetic_injection
        if is_synthetic != self.request_synthetic_injection:
            raise ValueError(
                "synthetic injection requires trigger='synthetic_injection' "
                "and explicit request_synthetic_injection=true"
            )
        return self


class SandboxRunHandle(BaseModel):
    run_id: uuid.UUID
    status: str
    container_id: str | None = None


class RunReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=4000)


class MembershipGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=255)
    role: Literal["owner", "admin", "maintainer", "reviewer", "viewer"]


class MembershipResponse(BaseModel):
    membership_id: int
    provider_installation_id: int
    subject: str
    role: str
    is_active: bool
    granted_by: str
    revoked_at: str | None = None


def _membership_response(membership: ProviderInstallationMembership) -> MembershipResponse:
    return MembershipResponse(
        membership_id=membership.id,
        provider_installation_id=membership.provider_installation_id,
        subject=membership.principal_subject,
        role=membership.role,
        is_active=membership.is_active,
        granted_by=f"{membership.granted_by_issuer}|{membership.granted_by_subject}",
        revoked_at=membership.revoked_at.isoformat() if membership.revoked_at else None,
    )


async def _get_active_repository(
    session: AsyncSession,
    repository_id: int,
) -> tuple[Repository, ProviderInstallation]:
    result = await session.execute(
        select(Repository, ProviderInstallation)
        .join(
            ProviderInstallation,
            ProviderInstallation.id == Repository.provider_installation_id,
        )
        .where(
            Repository.id == repository_id,
            ProviderInstallation.is_active.is_(True),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository is not linked to an active provider installation",
        )
    return row


@app.get(
    "/lab/admin/installations/{provider_installation_id}/memberships",
    response_model=list[MembershipResponse],
)
async def list_installation_memberships(
    provider_installation_id: int,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    if not is_lab_operator(principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Global Lab operator permission required")
    installation = await session.get(ProviderInstallation, provider_installation_id)
    if installation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider installation not found")
    result = await session.execute(
        select(ProviderInstallationMembership)
        .where(ProviderInstallationMembership.provider_installation_id == provider_installation_id)
        .order_by(ProviderInstallationMembership.principal_subject)
    )
    return [_membership_response(membership) for membership in result.scalars()]


@app.post("/lab/admin/installations/{provider_installation_id}/memberships", response_model=MembershipResponse)
async def create_installation_membership(
    provider_installation_id: int,
    req: MembershipGrantRequest,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    membership = await grant_installation_membership(
        session,
        provider_installation_id,
        req.subject,
        req.role,
        principal,
    )
    await session.commit()
    await session.refresh(membership)
    return _membership_response(membership)


@app.delete(
    "/lab/admin/installations/{provider_installation_id}/memberships/{membership_id}",
    response_model=MembershipResponse,
)
async def delete_installation_membership(
    provider_installation_id: int,
    membership_id: int,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    membership = await revoke_installation_membership(
        session,
        provider_installation_id,
        membership_id,
        principal,
    )
    await session.commit()
    await session.refresh(membership)
    return _membership_response(membership)


@app.post("/lab/runs", response_model=SandboxRunHandle)
async def create_sandbox_run(
    req: SandboxRunRequest,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    repository, installation = await _get_active_repository(session, req.repository_id)
    await require_installation_role(session, installation.id, principal, RUN_ROLES)

    if req.request_synthetic_injection and not (
        repository.sandbox_lab_opt_in
        and repository.sandbox_lab_consented_at is not None
        and repository.sandbox_lab_consent_actor_id
        and repository.sandbox_lab_consent_version
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This repository has not provided complete consent for synthetic injection",
        )

    # Intentionally fail closed. The runner still clones inside a network-
    # isolated container and lacks the complete durable lifecycle integration.
    # Do not accept or persist a run until host-side pinned cloning and verified
    # immutable archive transfer replace that unsafe/incomplete path.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Lab execution is disabled pending the pinned host-side clone, "
            "immutable source transfer, runner and result-persistence release gates"
        ),
    )


@app.get("/lab/runs/{run_id}", response_model=SandboxRunHandle)
async def get_sandbox_run(
    run_id: uuid.UUID,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(SandboxRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await require_installation_role(session, run.provider_installation_id, principal, READ_ROLES)
    return SandboxRunHandle(run_id=run.id, status=run.status, container_id=run.container_id)


@app.post("/lab/runs/{run_id}/review")
async def review_sandbox_run(
    run_id: uuid.UUID,
    req: RunReviewRequest,
    principal: LabPrincipal = Depends(get_current_lab_principal),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(SandboxRun).where(SandboxRun.id == run_id).with_for_update())
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await require_installation_role(session, run.provider_installation_id, principal, REVIEW_ROLES)
    if run.status != "awaiting_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is in status '{run.status}', not awaiting review",
        )

    reviewer_subject = f"{principal.issuer}|{principal.subject}"
    review = RunReview(
        sandbox_run_id=run.id,
        reviewed_by=reviewer_subject,
        decision=req.decision,
        notes=req.notes or None,
    )
    session.add(review)
    run.status = req.decision
    await session.commit()
    await session.refresh(review)

    return {
        "run_id": run.id,
        "review_id": review.id,
        "status": run.status,
        "reviewed_by": reviewer_subject,
    }
