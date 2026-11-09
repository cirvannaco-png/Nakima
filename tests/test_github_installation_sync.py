from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from githubapp.installation_sync import (
    require_active_github_repository_installation,
    sync_github_installation_event,
)
from models.provider_installation import ProviderInstallation
from models.provider_installation_membership import ProviderInstallationMembership
from models.repository import Repository


def _installation(installation_id="7001"):
    return {
        "id": installation_id,
        "account": {
            "id": 3001,
            "login": "example-org",
            "type": "Organization",
        },
    }


def _repository(repo_id=88001, full_name="example-org/service"):
    return {"id": repo_id, "full_name": full_name}


@pytest.mark.asyncio
async def test_installation_repositories_added_is_idempotent_and_uses_canonical_repository_id(db_session):
    payload = {
        "action": "added",
        "installation": _installation(),
        "repositories_added": [_repository()],
    }

    first = await sync_github_installation_event(db_session, "installation_repositories", payload)
    await db_session.commit()
    second = await sync_github_installation_event(db_session, "installation_repositories", payload)
    await db_session.commit()

    repository_rows = (
        (await db_session.execute(select(Repository).where(Repository.github_repo_id == 88001))).scalars().all()
    )
    installations = (
        (
            await db_session.execute(
                select(ProviderInstallation).where(
                    ProviderInstallation.provider == "github",
                    ProviderInstallation.external_installation_id == "7001",
                )
            )
        )
        .scalars()
        .all()
    )

    assert first["repositories_added"] == second["repositories_added"] == 1
    assert len(repository_rows) == 1
    assert repository_rows[0].id > 0
    assert repository_rows[0].full_name == "example-org/service"
    assert repository_rows[0].provider_installation_id == installations[0].id
    assert installations[0].is_active is True


@pytest.mark.asyncio
async def test_repository_removal_detaches_tenant_and_revokes_lab_consent(db_session):
    await sync_github_installation_event(
        db_session,
        "installation_repositories",
        {
            "action": "added",
            "installation": _installation(),
            "repositories_added": [_repository()],
        },
    )
    repository = await db_session.scalar(select(Repository).where(Repository.github_repo_id == 88001))
    assert repository is not None
    repository.sandbox_lab_opt_in = True
    repository.sandbox_lab_consented_at = datetime.now(UTC).replace(tzinfo=None)
    repository.sandbox_lab_consent_actor_id = "github-user:9001"
    repository.sandbox_lab_consent_version = "lab-consent-v1"
    await db_session.commit()

    result = await sync_github_installation_event(
        db_session,
        "installation_repositories",
        {
            "action": "removed",
            "installation": _installation(),
            "repositories_removed": [_repository()],
        },
    )
    await db_session.commit()

    assert result["repositories_removed"] == 1
    assert repository.provider_installation_id is None
    assert repository.sandbox_lab_opt_in is False
    assert repository.sandbox_lab_consented_at is None
    assert repository.sandbox_lab_consent_actor_id is None
    assert repository.sandbox_lab_consent_version is None


@pytest.mark.asyncio
async def test_installation_suspension_deactivates_tenant_and_revokes_consent(db_session):
    await sync_github_installation_event(
        db_session,
        "installation",
        {
            "action": "created",
            "installation": _installation(),
            "repositories": [_repository()],
        },
    )
    repository = await db_session.scalar(select(Repository).where(Repository.github_repo_id == 88001))
    installation = await db_session.scalar(
        select(ProviderInstallation).where(ProviderInstallation.external_installation_id == "7001")
    )
    assert repository is not None
    assert installation is not None
    repository.sandbox_lab_opt_in = True
    repository.sandbox_lab_consented_at = datetime.now(UTC).replace(tzinfo=None)
    repository.sandbox_lab_consent_actor_id = "github-user:9001"
    repository.sandbox_lab_consent_version = "lab-consent-v1"
    await db_session.commit()

    result = await sync_github_installation_event(
        db_session,
        "installation",
        {"action": "suspend", "installation": _installation()},
    )
    await db_session.commit()

    assert result["status"] == "synced"
    assert installation.is_active is False
    assert installation.deactivated_at is not None
    assert repository.provider_installation_id == installation.id
    assert repository.sandbox_lab_opt_in is False


@pytest.mark.asyncio
async def test_installation_deletion_detaches_repositories(db_session):
    await sync_github_installation_event(
        db_session,
        "installation",
        {
            "action": "created",
            "installation": _installation(),
            "repositories": [_repository()],
        },
    )
    repository = await db_session.scalar(select(Repository).where(Repository.github_repo_id == 88001))
    installation = await db_session.scalar(
        select(ProviderInstallation).where(ProviderInstallation.external_installation_id == "7001")
    )
    assert repository is not None
    assert installation is not None

    membership = ProviderInstallationMembership(
        provider_installation_id=installation.id,
        principal_issuer="https://identity.example.test/",
        principal_subject="tenant-owner-1",
        role="owner",
        granted_by_issuer="https://identity.example.test/",
        granted_by_subject="operator-1",
    )
    db_session.add(membership)
    await db_session.commit()

    await sync_github_installation_event(
        db_session,
        "installation",
        {"action": "deleted", "installation": _installation()},
    )
    await db_session.commit()

    assert installation.is_active is False
    assert repository.provider_installation_id is None
    assert repository.sandbox_lab_opt_in is False
    assert membership.is_active is False
    assert membership.revoked_at is not None
    assert membership.revoked_by_issuer == "urn:nakima:system"


@pytest.mark.asyncio
async def test_malformed_added_repository_fails_closed(db_session):
    with pytest.raises(ValueError, match="numeric id"):
        await sync_github_installation_event(
            db_session,
            "installation_repositories",
            {
                "action": "added",
                "installation": _installation(),
                "repositories_added": [{"full_name": "example-org/invalid"}],
            },
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_orphaned_removal_does_not_create_an_installation(db_session):
    result = await sync_github_installation_event(
        db_session,
        "installation_repositories",
        {
            "action": "removed",
            "installation": _installation("9999"),
            "repositories_removed": [_repository(99001, "example-org/orphan")],
        },
    )

    installations = (await db_session.execute(select(ProviderInstallation))).scalars().all()

    assert result["status"] == "ignored"
    assert installations == []


@pytest.mark.asyncio
async def test_unknown_installation_action_does_not_create_a_tenant(db_session):
    result = await sync_github_installation_event(
        db_session,
        "installation",
        {"action": "unexpected", "installation": _installation("9998")},
    )

    installations = (await db_session.execute(select(ProviderInstallation))).scalars().all()

    assert result["status"] == "ignored"
    assert installations == []


@pytest.mark.asyncio
async def test_normal_repository_webhook_requires_existing_active_installation_link(db_session):
    await sync_github_installation_event(
        db_session,
        "installation",
        {
            "action": "created",
            "installation": _installation(),
            "repositories": [_repository()],
        },
    )

    repository = await require_active_github_repository_installation(
        db_session,
        _installation(),
        _repository(),
    )
    assert repository.github_repo_id == 88001

    with pytest.raises(ValueError, match="not registered or is inactive"):
        await require_active_github_repository_installation(
            db_session,
            _installation("7002"),
            _repository(),
        )

    await sync_github_installation_event(
        db_session,
        "installation",
        {"action": "suspend", "installation": _installation()},
    )
    with pytest.raises(ValueError, match="not registered or is inactive"):
        await require_active_github_repository_installation(
            db_session,
            _installation(),
            _repository(),
        )


@pytest.mark.asyncio
async def test_repository_webhook_can_update_name_only_for_same_linked_repo(db_session):
    await sync_github_installation_event(
        db_session,
        "installation",
        {
            "action": "created",
            "installation": _installation(),
            "repositories": [_repository()],
        },
    )

    repository = await require_active_github_repository_installation(
        db_session,
        _installation(),
        _repository(88001, "example-org/renamed-service"),
    )
    assert repository.full_name == "example-org/renamed-service"
