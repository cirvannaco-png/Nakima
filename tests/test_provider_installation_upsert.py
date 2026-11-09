import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base
from models.provider_installation import ProviderInstallation
from models.repository import Repository
from models.task import Task  # noqa: F401
from orchestrator.workflow import (
    RepositoryIdentityConflictError,
    RepositoryProviderMetadataError,
    RepositoryTenantConflictError,
    WorkflowOrchestrator,
)


async def _wire_test_database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    import orchestrator.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "AsyncSessionLocal", session_factory)
    return engine, session_factory


def _payload(installation_id=501, repository_id=9001, full_name="example/repo", account_id=77):
    return {
        "installation": {
            "id": installation_id,
            "account": {
                "id": account_id,
                "login": "example",
                "type": "Organization",
            },
        },
        "repository": {
            "id": repository_id,
            "full_name": full_name,
        },
    }


@pytest.mark.asyncio
async def test_verified_webhook_upserts_provider_installation_and_repository(monkeypatch):
    engine, session_factory = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        first = await orchestrator._ensure_repository("example/repo", provider_payload=_payload())
        second = await orchestrator._ensure_repository(
            "example/repo",
            provider_payload=_payload(full_name="example/repo"),
        )

        assert first.id == second.id
        assert first.github_repo_id == 9001
        assert first.provider_installation_id == second.provider_installation_id

        async with session_factory() as session:
            installations = (await session.execute(select(ProviderInstallation))).scalars().all()
            repositories = (await session.execute(select(Repository))).scalars().all()

        assert len(installations) == 1
        assert installations[0].provider == "github"
        assert installations[0].external_installation_id == "501"
        assert installations[0].account_external_id == "77"
        assert len(repositories) == 1
        assert repositories[0].provider_installation_id == installations[0].id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_cannot_be_reassigned_to_another_provider_installation(monkeypatch):
    engine, _ = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        await orchestrator._ensure_repository("example/repo", provider_payload=_payload())

        with pytest.raises(RepositoryTenantConflictError):
            await orchestrator._ensure_repository(
                "example/repo",
                provider_payload=_payload(installation_id=502),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_name_cannot_be_rebound_to_another_provider_repository_id(monkeypatch):
    engine, _ = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        await orchestrator._ensure_repository("example/repo", provider_payload=_payload())

        with pytest.raises(RepositoryIdentityConflictError):
            await orchestrator._ensure_repository(
                "example/repo",
                provider_payload=_payload(repository_id=9002),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_rename_updates_only_the_same_provider_repository(monkeypatch):
    engine, session_factory = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        original = await orchestrator._ensure_repository("example/repo", provider_payload=_payload())
        renamed = await orchestrator._ensure_repository(
            "example/renamed-repo",
            provider_payload=_payload(full_name="example/renamed-repo"),
        )

        assert original.id == renamed.id
        assert renamed.full_name == "example/renamed-repo"

        async with session_factory() as session:
            count = (await session.execute(select(Repository))).scalars().all()
        assert len(count) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_webhook_repository_upsert_fails_closed_without_stable_ids(monkeypatch):
    engine, _ = await _wire_test_database(monkeypatch)
    try:
        with pytest.raises(RepositoryProviderMetadataError):
            await WorkflowOrchestrator()._ensure_repository(
                "example/repo",
                provider_payload={"installation": {"id": 501}, "repository": {"full_name": "example/repo"}},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_installation_account_identity_cannot_be_silently_changed(monkeypatch):
    engine, _ = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        await orchestrator._ensure_repository("example/repo", provider_payload=_payload())

        with pytest.raises(RepositoryTenantConflictError):
            await orchestrator._ensure_repository(
                "example/repo",
                provider_payload=_payload(account_id=88),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_duplicate_non_null_github_repository_ids(monkeypatch):
    engine, session_factory = await _wire_test_database(monkeypatch)
    try:
        orchestrator = WorkflowOrchestrator()
        repository = await orchestrator._ensure_repository("example/repo", provider_payload=_payload())

        async with session_factory() as session:
            duplicate = Repository(
                full_name="example/duplicate",
                github_repo_id=repository.github_repo_id,
                provider_installation_id=repository.provider_installation_id,
            )
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
