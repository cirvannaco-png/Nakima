from pathlib import Path
import pytest
from attachments.validation import inspect_media_upload
from cicd.profile import CICDProfile, render_pipeline
from memory.workspace_guidance import load_approved_workspace_guidance
from monitoring import redact_log_message

def test_media_validation_uses_file_signature_and_sanitizes_filename():
    payload = b"\x89PNG\r\n\x1a\n" + b"image-data"
    filename, media_type = inspect_media_upload("../../bad name.png", payload, "image/png")
    assert filename == "bad-name.png"
    assert media_type == "image/png"

def test_media_validation_rejects_mime_mismatch():
    with pytest.raises(ValueError, match="does not match"):
        inspect_media_upload("screenshot.png", b"\x89PNG\r\n\x1a\nx", "image/jpeg")

def test_media_validation_rejects_svg_and_unknown_content():
    with pytest.raises(ValueError, match="Unsupported media"):
        inspect_media_upload("image.svg", b"<svg></svg>", "image/svg+xml")

def test_workspace_guidance_reads_only_repository_file(tmp_path: Path):
    guidance_dir = tmp_path / ".nakima"
    guidance_dir.mkdir()
    (guidance_dir / "workspace-guidance.md").write_text("Use async SQLAlchemy.", encoding="utf-8")
    assert load_approved_workspace_guidance(tmp_path) == "Use async SQLAlchemy."

def test_workspace_guidance_missing_file_is_empty(tmp_path: Path):
    assert load_approved_workspace_guidance(tmp_path) == ""

@pytest.mark.parametrize(
    ("engine", "expected_path"),
    [
        ("github_actions", ".github/workflows/nakima-ci.yml"),
        ("gitea_actions", ".github/workflows/nakima-ci.yml"),
        ("gitlab_ci", ".gitlab-ci.yml"),
        ("bitbucket_pipelines", "bitbucket-pipelines.yml"),
        ("generic_git", ".nakima/ci.sh"),
    ],
)
def test_cicd_profile_renders_provider_specific_validation(engine, expected_path):
    rendered = render_pipeline(CICDProfile(engine=engine))
    assert rendered["path"] == expected_path
    assert "pytest --tb=short -q" in rendered["content"]

def test_cicd_profile_rejects_empty_branch_list():
    with pytest.raises(ValueError):
        CICDProfile(branches=[])

def test_generated_ci_never_contains_deployment_command():
    profile = CICDProfile(deployment_command="deploy --production")
    assert "deploy --production" not in render_pipeline(profile)["content"]

def test_log_redaction_masks_common_credentials():
    message = redact_log_message("Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456 token=secret-value")
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in message
    assert "secret-value" not in message
    assert "[REDACTED]" in message
