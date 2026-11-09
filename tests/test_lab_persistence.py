import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.lab import ModelCandidateFix, RunReview, SandboxRun
from models.provider_installation import ProviderInstallation
from models.repository import Repository


@pytest.mark.asyncio
async def test_lab_run_review_and_candidate_records_use_canonical_repository(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="lab-target-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/lab-target", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="ci_failure",
        source_commit_sha="a" * 40,
    )
    db_session.add(run)
    await db_session.flush()

    assert run.status == "queued"
    # A DB row must not claim isolation until the orchestrator verifies it.
    assert run.network_isolated is False

    candidate = ModelCandidateFix(
        sandbox_run_id=run.id,
        provider="github",
        model="openai/gpt-4o-mini",
        candidate_diff="diff --git a/app.py b/app.py",
        candidate_status="tested",
        test_suite_passed=True,
        applied_commit_sha="d" * 40,
        tested_at=datetime.now(UTC),
        test_results={"passed": 42, "failed": 0},
    )
    review = RunReview(
        sandbox_run_id=run.id,
        reviewed_by="github-user:9001",
        decision="approved",
        notes="Reviewed candidate evidence",
    )
    db_session.add_all([candidate, review])
    await db_session.commit()

    stored_run = await db_session.scalar(select(SandboxRun).where(SandboxRun.id == run.id))
    assert stored_run is not None
    assert stored_run.repository_id == repository.id
    assert stored_run.full_test_suite_passed is None

    stored_candidate = await db_session.scalar(
        select(ModelCandidateFix).where(ModelCandidateFix.sandbox_run_id == run.id)
    )
    assert stored_candidate is not None
    assert stored_candidate.test_suite_passed is True
    assert stored_candidate.retained_for_training is False

    stored_review = await db_session.scalar(select(RunReview).where(RunReview.sandbox_run_id == run.id))
    assert stored_review is not None
    assert stored_review.decision == "approved"


@pytest.mark.asyncio
async def test_candidate_cannot_be_selected_without_passing_test_evidence(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="candidate-gate-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/candidate-gate", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="b" * 40,
    )
    db_session.add(run)
    await db_session.flush()

    invalid = ModelCandidateFix(
        sandbox_run_id=run.id,
        provider="github",
        candidate_diff="candidate patch",
        candidate_status="selected",
        test_suite_passed=None,
    )
    db_session.add(invalid)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_synthetic_injection_requires_matching_run_trigger(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="synthetic-gate-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/synthetic-gate", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    invalid = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="ci_failure",
        source_commit_sha="c" * 40,
        synthetic_injection_used=True,
    )
    db_session.add(invalid)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_run_tenant_snapshot_survives_repository_detachment(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="detach-history-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/detach-history", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="e" * 40,
    )
    db_session.add(run)
    await db_session.commit()

    # Provider removal revokes the current repository link and consent, but
    # the historical run retains the tenant that owned it when created.
    repository.provider_installation_id = None
    repository.sandbox_lab_opt_in = False
    repository.sandbox_lab_consented_at = None
    repository.sandbox_lab_consent_actor_id = None
    repository.sandbox_lab_consent_version = None
    await db_session.commit()

    stored_run = await db_session.scalar(select(SandboxRun).where(SandboxRun.id == run.id))
    assert stored_run is not None
    assert stored_run.repository_id == repository.id
    assert stored_run.provider_installation_id == installation.id
    assert stored_run.repository.provider_installation_id is None


@pytest.mark.asyncio
async def test_only_one_candidate_can_be_selected_for_a_run(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="one-winner-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/one-winner", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="f" * 40,
    )
    db_session.add(run)
    await db_session.flush()

    timestamp = datetime.now(UTC)
    candidates = [
        ModelCandidateFix(
            sandbox_run_id=run.id,
            provider="github",
            candidate_diff=f"candidate patch {index}",
            candidate_status="selected",
            test_suite_passed=True,
            applied_commit_sha=str(index) * 40,
            tested_at=timestamp,
            test_results={"passed": 15, "failed": 0},
        )
        for index in (1, 2)
    ]
    db_session.add_all(candidates)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_tested_candidate_requires_commit_and_full_test_evidence(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="tested-evidence-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/tested-evidence", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="1" * 40,
    )
    db_session.add(run)
    await db_session.flush()

    invalid = ModelCandidateFix(
        sandbox_run_id=run.id,
        provider="github",
        candidate_diff="candidate patch without applied-worktree evidence",
        candidate_status="tested",
        test_suite_passed=True,
        test_results={"passed": 15, "failed": 0},
    )
    db_session.add(invalid)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_postgres_trigger_enforces_active_installation_and_synthetic_consent():
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        try:
            async with engine.connect() as connection:
                await connection.exec_driver_sql("SELECT 1")
        except DBAPIError:
            pytest.skip("PostgreSQL is not available for migration-trigger integration tests")

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            installation = ProviderInstallation(
                provider="github",
                external_installation_id=f"trigger-test-{uuid.uuid4()}",
                is_active=True,
            )
            session.add(installation)
            await session.flush()

            repository = Repository(
                full_name=f"example/trigger-{uuid.uuid4().hex}",
                provider_installation_id=installation.id,
            )
            session.add(repository)
            await session.commit()
            repository_id = repository.id
            installation_id = installation.id

            invalid = SandboxRun(
                repository_id=repository_id,
                provider_installation_id=installation_id,
                trigger="synthetic_injection",
                source_commit_sha="2" * 40,
                synthetic_injection_used=True,
            )
            session.add(invalid)
            with pytest.raises(DBAPIError):
                await session.commit()
            await session.rollback()
            repository = await session.get(Repository, repository_id)
            installation = await session.get(ProviderInstallation, installation_id)
            assert repository is not None
            assert installation is not None

            repository.sandbox_lab_opt_in = True
            repository.sandbox_lab_consented_at = datetime.now(UTC).replace(tzinfo=None)
            repository.sandbox_lab_consent_actor_id = "test-user:tenant-owner"
            repository.sandbox_lab_consent_version = "lab-consent-v1"
            await session.commit()

            valid = SandboxRun(
                repository_id=repository_id,
                provider_installation_id=installation_id,
                trigger="synthetic_injection",
                source_commit_sha="3" * 40,
                synthetic_injection_used=True,
            )
            session.add(valid)
            await session.commit()
            assert valid.id is not None

            # The run retains its original tenant snapshot when the provider
            # later removes repository access and consent is revoked.
            repository.provider_installation_id = None
            repository.sandbox_lab_opt_in = False
            repository.sandbox_lab_consented_at = None
            repository.sandbox_lab_consent_actor_id = None
            repository.sandbox_lab_consent_version = None
            await session.commit()

            stored = await session.get(SandboxRun, valid.id)
            assert stored is not None
            assert stored.provider_installation_id == installation.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_network_isolation_claim_requires_container_evidence(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="isolation-evidence-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/isolation-evidence", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="4" * 40,
        network_isolated=True,
    )
    db_session.add(run)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_candidate_training_retention_is_database_disabled(db_session):
    installation = ProviderInstallation(provider="github", external_installation_id="training-retention-install")
    db_session.add(installation)
    await db_session.flush()
    repository = Repository(full_name="example/training-retention", provider_installation_id=installation.id)
    db_session.add(repository)
    await db_session.flush()

    run = SandboxRun(
        repository_id=repository.id,
        provider_installation_id=installation.id,
        trigger="manual",
        source_commit_sha="5" * 40,
    )
    db_session.add(run)
    await db_session.flush()

    candidate = ModelCandidateFix(
        sandbox_run_id=run.id,
        provider="github",
        candidate_diff="private tenant-scoped patch",
        retained_for_training=True,
    )
    db_session.add(candidate)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
