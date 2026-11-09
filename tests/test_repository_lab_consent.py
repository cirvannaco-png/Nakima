from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.provider_installation import ProviderInstallation
from models.repository import Repository


@pytest.mark.asyncio
async def test_legacy_repository_defaults_to_lab_opt_out(db_session):
    repository = Repository(full_name="example/legacy")
    db_session.add(repository)
    await db_session.commit()

    stored = await db_session.scalar(select(Repository).where(Repository.full_name == "example/legacy"))
    assert stored is not None
    assert stored.id > 0
    assert stored.provider_installation_id is None
    assert stored.sandbox_lab_opt_in is False
    assert stored.sandbox_lab_consented_at is None
    assert stored.sandbox_lab_consent_actor_id is None
    assert stored.sandbox_lab_consent_version is None


@pytest.mark.asyncio
async def test_lab_opt_in_requires_installation_and_complete_consent_record(db_session):
    invalid = Repository(
        full_name="example/incomplete-consent",
        sandbox_lab_opt_in=True,
    )
    db_session.add(invalid)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    installation = ProviderInstallation(
        provider="github",
        external_installation_id="7001",
        account_external_id="3001",
        account_login="example-org",
        account_type="Organization",
    )
    db_session.add(installation)
    await db_session.flush()

    valid = Repository(
        full_name="example/consented",
        provider_installation_id=installation.id,
        sandbox_lab_opt_in=True,
        sandbox_lab_consented_at=datetime.now(UTC).replace(tzinfo=None),
        sandbox_lab_consent_actor_id="github-user:9001",
        sandbox_lab_consent_version="lab-consent-v1",
    )
    db_session.add(valid)
    await db_session.commit()

    stored = await db_session.scalar(select(Repository).where(Repository.full_name == "example/consented"))
    assert stored is not None
    assert stored.sandbox_lab_opt_in is True
    assert stored.provider_installation_id == installation.id
    assert stored.sandbox_lab_consent_actor_id == "github-user:9001"
