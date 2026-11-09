from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.repository import Repository


@pytest.mark.asyncio
async def test_legacy_repository_defaults_to_lab_opt_out(db_session):
    repository = Repository(full_name="example/legacy")
    db_session.add(repository)
    await db_session.commit()

    stored = await db_session.scalar(select(Repository).where(Repository.full_name == "example/legacy"))
    assert stored is not None
    assert stored.id > 0
    assert stored.github_installation_id is None
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

    valid = Repository(
        full_name="example/consented",
        github_installation_id=7001,
        sandbox_lab_opt_in=True,
        sandbox_lab_consented_at=datetime.now(UTC).replace(tzinfo=None),
        sandbox_lab_consent_actor_id=9001,
        sandbox_lab_consent_version="lab-consent-v1",
    )
    db_session.add(valid)
    await db_session.commit()

    stored = await db_session.scalar(select(Repository).where(Repository.full_name == "example/consented"))
    assert stored is not None
    assert stored.sandbox_lab_opt_in is True
    assert stored.github_installation_id == 7001
    assert stored.sandbox_lab_consent_actor_id == 9001
