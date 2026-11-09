import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestrator.main import RunReviewRequest, SandboxRunRequest, app


def test_lab_run_request_uses_canonical_integer_repository_id():
    request = SandboxRunRequest(
        repository_id=42,
        source_commit_sha="a" * 40,
        trigger="manual",
    )
    assert request.repository_id == 42
    assert not hasattr(request, "organization_id")


def test_lab_run_request_rejects_legacy_or_client_supplied_tenant_ids():
    with pytest.raises(ValidationError):
        SandboxRunRequest.model_validate(
            {
                "repository_id": 42,
                "organization_id": "7f2c0e0a-26a2-4e1e-a9a8-2f8c4ec8e3b2",
                "source_commit_sha": "a" * 40,
                "trigger": "manual",
            }
        )


def test_review_request_rejects_caller_supplied_reviewer_identity():
    with pytest.raises(ValidationError):
        RunReviewRequest.model_validate(
            {
                "decision": "approved",
                "reviewer_user_id": "attacker-selected-user",
            }
        )


def test_unconfigured_or_unauthenticated_lab_api_fails_closed():
    client = TestClient(app)
    response = client.post(
        "/lab/runs",
        json={
            "repository_id": 42,
            "source_commit_sha": "a" * 40,
            "trigger": "manual",
        },
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
