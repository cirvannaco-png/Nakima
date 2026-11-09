from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from lab.auth import LabPrincipal
from models.provider_installation import ProviderInstallation
from models.provider_installation_membership import ProviderInstallationMembership


INSTALLATION_ROLES = {"owner", "admin", "maintainer", "reviewer", "viewer"}
RUN_ROLES = {"owner", "admin", "maintainer"}
REVIEW_ROLES = {"owner", "admin", "reviewer"}
READ_ROLES = INSTALLATION_ROLES


def is_lab_operator(principal: LabPrincipal) -> bool:
    """Global operators are explicitly allowlisted by immutable OIDC subject."""
    if principal.issuer != settings.LAB_OIDC_ISSUER:
        return False
    allowed_subjects = {subject.strip() for subject in settings.LAB_OIDC_ADMIN_SUBJECTS.split(",") if subject.strip()}
    return principal.subject in allowed_subjects


async def require_installation_role(
    session: AsyncSession,
    provider_installation_id: int,
    principal: LabPrincipal,
    allowed_roles: set[str],
) -> ProviderInstallationMembership:
    result = await session.execute(
        select(ProviderInstallationMembership)
        .join(
            ProviderInstallation,
            ProviderInstallation.id == ProviderInstallationMembership.provider_installation_id,
        )
        .where(
            ProviderInstallationMembership.provider_installation_id == provider_installation_id,
            ProviderInstallationMembership.principal_issuer == principal.issuer,
            ProviderInstallationMembership.principal_subject == principal.subject,
            ProviderInstallationMembership.is_active.is_(True),
            ProviderInstallationMembership.role.in_(allowed_roles),
            ProviderInstallation.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have the required role for this provider installation",
        )
    return membership


async def grant_installation_membership(
    session: AsyncSession,
    provider_installation_id: int,
    principal_subject: str,
    role: str,
    granted_by: LabPrincipal,
) -> ProviderInstallationMembership:
    """Create/reactivate an explicit membership. Caller must already be global operator."""
    if not is_lab_operator(granted_by):
        raise HTTPException(status_code=403, detail="Global Lab operator permission required")
    if role not in INSTALLATION_ROLES:
        raise HTTPException(status_code=422, detail="Unsupported installation role")
    if not isinstance(principal_subject, str) or not principal_subject.strip() or len(principal_subject) > 255:
        raise HTTPException(status_code=422, detail="A valid OIDC subject is required")

    installation = await session.scalar(
        select(ProviderInstallation).where(ProviderInstallation.id == provider_installation_id).with_for_update()
    )
    if installation is None or not installation.is_active:
        raise HTTPException(status_code=404, detail="Active provider installation not found")

    result = await session.execute(
        select(ProviderInstallationMembership)
        .where(
            ProviderInstallationMembership.provider_installation_id == provider_installation_id,
            ProviderInstallationMembership.principal_issuer == granted_by.issuer,
            ProviderInstallationMembership.principal_subject == principal_subject.strip(),
            ProviderInstallationMembership.is_active.is_(True),
        )
        .with_for_update()
    )
    active_membership = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if active_membership is not None and active_membership.role == role:
        return active_membership

    if active_membership is not None:
        # A role change closes the previous grant and creates a new immutable
        # grant record. Historical issuer/subject, grantor and revoke evidence
        # remain queryable instead of being overwritten.
        active_membership.is_active = False
        active_membership.revoked_by_issuer = granted_by.issuer
        active_membership.revoked_by_subject = granted_by.subject
        active_membership.revocation_reason = "role_changed"
        active_membership.revoked_at = now
        active_membership.updated_at = now
        # Release the partial unique active-grant index before inserting its
        # replacement row in the same transaction.
        await session.flush()

    membership = ProviderInstallationMembership(
        provider_installation_id=provider_installation_id,
        principal_issuer=granted_by.issuer,
        principal_subject=principal_subject.strip(),
        role=role,
        is_active=True,
        granted_by_issuer=granted_by.issuer,
        granted_by_subject=granted_by.subject,
        granted_at=now,
    )
    session.add(membership)
    await session.flush()
    return membership


async def revoke_installation_membership(
    session: AsyncSession,
    provider_installation_id: int,
    membership_id: int,
    revoked_by: LabPrincipal,
) -> ProviderInstallationMembership:
    if not is_lab_operator(revoked_by):
        raise HTTPException(status_code=403, detail="Global Lab operator permission required")

    membership = await session.scalar(
        select(ProviderInstallationMembership)
        .where(
            ProviderInstallationMembership.id == membership_id,
            ProviderInstallationMembership.provider_installation_id == provider_installation_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Installation membership not found")
    if membership.is_active:
        membership.is_active = False
        membership.revoked_by_issuer = revoked_by.issuer
        membership.revoked_by_subject = revoked_by.subject
        membership.revocation_reason = "operator_revoked"
        membership.revoked_at = datetime.now(UTC)
        membership.updated_at = membership.revoked_at
    await session.flush()
    return membership
