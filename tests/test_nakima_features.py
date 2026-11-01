from cicd.profile import CICDProfile, render_pipeline
from attachments.validation import inspect_media_upload
from monitoring import redact_log_message


def test_attachment_validation_uses_file_signature_and_safe_name():
    name, mime = inspect_media_upload("../../capture.PNG", bytes.fromhex("89504e470d0a1a0a") + b"payload", "image/png")
    assert name == "capture.png"
    assert mime == "image/png"


def test_attachment_validation_rejects_mismatched_content_type():
    import pytest
    with pytest.raises(ValueError):
        inspect_media_upload("capture.png", b"not a png", "image/png")


def test_ci_profile_renders_repository_specific_github_workflow():
    rendered = render_pipeline(CICDProfile(engine="github_actions", branches=["main"]))
    assert rendered["path"] == ".github/workflows/nakima-ci.yml"
    assert "actions/checkout@v4" in rendered["content"]
    assert "pytest --tb=short -q" in rendered["content"]


def test_ci_profile_renders_gitlab_and_bitbucket():
    gitlab = render_pipeline(CICDProfile(engine="gitlab_ci"))
    bitbucket = render_pipeline(CICDProfile(engine="bitbucket_pipelines"))
    assert gitlab["path"] == ".gitlab-ci.yml"
    assert "merge_request_event" in gitlab["content"]
    assert bitbucket["path"] == "bitbucket-pipelines.yml"


def test_ci_profile_rejects_empty_branch_set():
    import pytest
    with pytest.raises(ValueError):
        CICDProfile(branches=[])


def test_monitoring_redacts_credentials():
    message = redact_log_message("Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert "ghp_" not in message
    assert "[REDACTED]" in message
