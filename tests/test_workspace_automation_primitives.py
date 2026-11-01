from pathlib import Path

import pytest

from attachments.validation import validate_attachment
from cicd.profiles import CiProfile, render_github_actions
from monitoring.redaction import redact_sensitive_text
from workspace.guidance import load_approved_guidance


def test_attachment_checks_signature_and_sanitizes_filename():
    result = validate_attachment("../../screen shot.png", "image/png", b"\x89PNG\r\n\x1a\npayload")
    assert result.filename == "screen_shot.png"
    assert result.size_bytes > 0
    assert len(result.sha256) == 64


def test_attachment_rejects_mismatched_signature_and_unknown_type():
    with pytest.raises(ValueError):
        validate_attachment("x.png", "image/png", b"not a png")
    with pytest.raises(ValueError):
        validate_attachment("x.svg", "image/svg+xml", b"<svg/>")


def test_attachment_rejects_empty_and_oversized_content():
    with pytest.raises(ValueError):
        validate_attachment("empty.png", "image/png", b"")
    with pytest.raises(ValueError):
        validate_attachment("large.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * (20 * 1024 * 1024))


def test_workspace_guidance_only_reads_expected_file(tmp_path: Path):
    guidance = tmp_path / ".nakima" / "workspace-guidance.md"
    guidance.parent.mkdir()
    guidance.write_text("Approved conventions", encoding="utf-8")
    assert load_approved_guidance(tmp_path) == "Approved conventions"
    assert load_approved_guidance(tmp_path / "missing") == ""


def test_workspace_guidance_rejects_symlink(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("do not load", encoding="utf-8")
    root = tmp_path / "repo"
    (root / ".nakima").mkdir(parents=True)
    (root / ".nakima" / "workspace-guidance.md").symlink_to(outside)
    assert load_approved_guidance(root) == ""


def test_redaction_removes_credentials_and_bounds_text():
    value = "Authorization: Bearer abc123 api_key=secret ghp_abcdefghijklmnopqrstuv"
    result = redact_sensitive_text(value, limit=200)
    assert "abc123" not in result
    assert "secret" not in result
    assert "ghp_" not in result
    assert len(redact_sensitive_text("x" * 50, limit=10)) == 10


def test_ci_profile_is_validated_and_renders_fixed_commands():
    rendered = render_github_actions(CiProfile(provider="github-actions"))
    assert "permissions:\n  contents: read" in rendered
    assert "pytest --tb=short -q" in rendered
    assert "pull_request:" in rendered
    with pytest.raises(ValueError):
        render_github_actions(CiProfile(provider="github-actions", default_branch="../evil"))
    with pytest.raises(ValueError):
        render_github_actions(CiProfile(provider="gitlab-ci"))
