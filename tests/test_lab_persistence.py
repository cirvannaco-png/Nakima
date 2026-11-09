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
