import pytest
from fastapi import HTTPException
from sqlalchemy import select

from lab.auth import LabPrincipal
from lab.authorization import (
    READ_ROLES,
    REVIEW_ROLES,
    RUN_ROLES,
    grant_installation_membership,
    require_installation_role,
    revoke_installation_membership,
)
from models.provider_installation import ProviderInstallation
from models.provider_installation_membership import ProviderInstallationMembership


@pytest.fixture
def principals(monkeypatch):
    issuer = "https://identity.example.test/"
    monkeypatch.setattr("lab.authorization.settings.LAB_OIDC_ISSUER", issuer)
    monkeypatch.setattr("lab.authorization.settings.LAB_OIDC_ADMIN_SUBJECTS", "operator-1")
    return {
        "operator": LabPrincipal(issuer=issuer, subject="operator-1"),
        "maintainer": LabPrincipal(issuer=issuer, subject="developer-2"),
        "reviewer": LabPrincipal(issuer=issuer, subject="reviewer-3"),
    }

@pytest.mark.asyncio
async def test_membership_roles_are_scoped_to_exact_installation(db_session, principals):
    first = ProviderInstallation(provider="github", external_installation_id="tenant-first")
    second = ProviderInstallation(provider="gitlab", external_installation_id="tenant-second")
    db_session.add_all([first, second])
    await db_session.flush()

    membership = ProviderInstallationMembership(
        provider_installation_id=first.id,
        principal_issuer=principals["maintainer"].issuer,
        principal_subject=principals["maintainer"].subject,
        role="maintainer",
        granted_by_issuer=principals["operator"].issuer,
        granted_by_subject=principals["operator"].subject,
    )
    db_session.add(membership)
    await db_session.commit()

    authorized = await require_installation_role(db_session, first.id, principals["maintainer"], RUN_ROLES)
    assert authorized.role == "maintainer"

    with pytest.raises(HTTPException) as denied:
        await require_installation_role(db_session, second.id, principals["maintainer"], RUN_ROLES)
    assert denied.value.status_code == 403

@pytest.mark.asyncio
async def test_reviewer_cannot_create_runs_and_maintainer_cannot_review(db_session, principals):
    installation = ProviderInstallation(provider="github", external_installation_id="role-boundaries")
    db_session.add(installation)
    await db_session.flush()
    rows = [
        ProviderInstallationMembership(
            provider_installation_id=installation.id,
            principal_issuer=principals["reviewer"].issuer,
            principal_subject=principals["reviewer"].subject,
            role="reviewer",
            granted_by_issuer=principals["operator"].issuer,
            granted_by_subject=principals["operator"].subject,
        ),
        ProviderInstallationMembership(
            provider_installation_id=installation.id,
            principal_issuer=principals["maintainer"].issuer,
            principal_subject=principals["maintainer"].subject,
            role="maintainer",
            granted_by_issuer=principals["operator"].issuer,
            granted_by_subject=principals["operator"].subject,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    reviewer = await require_installation_role(db_session, installation.id, principals["reviewer"], REVIEW_ROLES)
    assert reviewer.role == "reviewer"

    with pytest.raises(HTTPException) as reviewer_denied:
        await require_installation_role(db_session, installation.id, principals["reviewer"], RUN_ROLES)
    assert reviewer_denied.value.status_code == 403

    with pytest.raises(HTTPException) as maintainer_denied:
        await require_installation_role(db_session, installation.id, principals["maintainer"], REVIEW_ROLES)
    assert maintainer_denied.value.status_code == 403

@pytest.mark.asyncio
async def test_global_operator_can_grant_and_revoke_membership_with_audit(db_session, principals):
    installation = ProviderInstallation(provider="github", external_installation_id="membership-audit")
    db_session.add(installation)
    await db_session.flush()

    membership = await grant_installation_membership(
        db_session,
        installation.id,
        principals["maintainer"].subject,
        "maintainer",
        principals["operator"],
    )
    await db_session.commit()

    assert membership.is_active is True
    assert membership.granted_by_subject == "operator-1"
    assert membership.revoked_at is None

    revoked = await revoke_installation_membership(
        db_session,
        installation.id,
        membership.id,
        principals["operator"],
    )
    await db_session.commit()

    assert revoked.is_active is False
    assert revoked.revoked_by_subject == "operator-1"
    assert revoked.revocation_reason == "operator_revoked"
    assert revoked.revoked_at is not None
    with pytest.raises(HTTPException):
        await require_installation_role(db_session, installation.id, principals["maintainer"], READ_ROLES)

@pytest.mark.asyncio
async def test_non_operator_cannot_grant_installation_membership(db_session, principals):
    installation = ProviderInstallation(provider="github", external_installation_id="operator-only")
    db_session.add(installation)
    await db_session.flush()

    with pytest.raises(HTTPException) as denied:
        await grant_installation_membership(
            db_session,
            installation.id,
            "another-user",
            "viewer",
            principals["maintainer"],
        )
    assert denied.value.status_code == 403

@pytest.mark.asyncio
async def test_inactive_installation_denies_even_active_membership(db_session, principals):
    installation = ProviderInstallation(
        provider="github",
        external_installation_id="suspended-tenant",
        is_active=False,
    )
    db_session.add(installation)
    await db_session.flush()
    db_session.add(
        ProviderInstallationMembership(
            provider_installation_id=installation.id,
            principal_issuer=principals["maintainer"].issuer,
            principal_subject=principals["maintainer"].subject,
            role="owner",
            granted_by_issuer=principals["operator"].issuer,
            granted_by_subject=principals["operator"].subject,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as denied:
        await require_installation_role(db_session, installation.id, principals["maintainer"], READ_ROLES)
    assert denied.value.status_code == 403

@pytest.mark.asyncio
async def test_role_change_creates_a_new_grant_and_preserves_revocation_history(db_session, principals):
    installation = ProviderInstallation(provider="github", external_installation_id="membership-role-history")
    db_session.add(installation)
    await db_session.flush()

    original = await grant_installation_membership(
        db_session,
        installation.id,
        principals["maintainer"].subject,
        "viewer",
        principals["operator"],
    )
    await db_session.commit()

    promoted = await grant_installation_membership(
        db_session,
        installation.id,
        principals["maintainer"].subject,
        "maintainer",
        principals["operator"],
    )
    await db_session.commit()

    assert promoted.id != original.id
    assert promoted.role == "maintainer"
    assert promoted.is_active is True
    assert original.is_active is False
    assert original.revocation_reason == "role_changed"
    assert original.revoked_by_subject == "operator-1"
    assert original.revoked_at is not None

    history = (
        (
            await db_session.execute(
                select(ProviderInstallationMembership)
                .where(
                    ProviderInstallationMembership.provider_installation_id == installation.id,
                    ProviderInstallationMembership.principal_subject == principals["maintainer"].subject,
                )
                .order_by(ProviderInstallationMembership.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 2

@pytest.mark.asyncio
async def test_regrant_same_role_is_idempotent(db_session, principals):
    installation = ProviderInstallation(provider="github", external_installation_id="membership-idempotent")
    db_session.add(installation)
    await db_session.flush()

    first = await grant_installation_membership(
        db_session,
        installation.id,
        principals["maintainer"].subject,
        "maintainer",
        principals["operator"],
    )
    await db_session.commit()

    second = await grant_installation_membership(
        db_session,
        installation.id,
        principals["maintainer"].subject,
        "maintainer",
        principals["operator"],
    )
    await db_session.commit()

    records = (
        (
            await db_session.execute(
                select(ProviderInstallationMembership).where(
                    ProviderInstallationMembership.provider_installation_id == installation.id,
                    ProviderInstallationMembership.principal_subject == principals["maintainer"].subject,
                )
            )
        )
        .scalars()
        .all()
    )
    assert first.id == second.id
    assert len(records) == 1
