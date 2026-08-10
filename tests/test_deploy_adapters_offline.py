"""
Offline unit tests for adapter validate()/plan()/rollback() logic that does not
require a live platform or an installed cloud SDK. These exercise the pure
decision paths: required-field validation, risk classification and the
rollback guard rails.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.adapters.gce import GCEAdapter  # noqa: E402
from deploy_agent.adapters.gcp import GCPAdapter  # noqa: E402
from deploy_agent.adapters.huggingface import HuggingFaceAdapter  # noqa: E402
from deploy_agent.models import DeployConfig, DeployRun, RiskLevel  # noqa: E402


def _config(**kwargs):
    base = {"platform": "x", "project_ref": "proj", "artifact_path": "/tmp"}
    base.update(kwargs)
    return DeployConfig(**base)


# --- GCP (Cloud Run) -------------------------------------------------------


def test_gcp_validate_reports_all_missing_inputs():
    result = GCPAdapter(credentials={}).validate(_config(project_ref=""))
    joined = " ".join(result.errors)
    assert not result.ok
    assert "service_account_json" in joined
    assert "project_id" in joined
    assert "region" in joined
    assert "image" in joined
    assert "project_ref" in joined


def test_gcp_plan_is_reversible_and_reports_traffic_split():
    adapter = GCPAdapter(credentials={"region": "us-central1"})
    plan = adapter.plan(_config(extra={"image": "gcr.io/p/i:1", "traffic_percent": 10}))
    assert plan.risk is RiskLevel.MEDIUM
    assert plan.reversible and not plan.destructive
    assert plan.metadata["traffic_percent"] == 10
    assert any("10% traffic" in change for change in plan.changes)
    assert any("remainder stays" in change for change in plan.changes)


def test_gcp_plan_full_traffic_has_no_remainder_note():
    plan = GCPAdapter(credentials={"region": "eu-west1"}).plan(_config(extra={"image": "img"}))
    assert plan.metadata["traffic_percent"] == 100
    assert not any("remainder stays" in change for change in plan.changes)


def test_gcp_rollback_without_previous_revision_fails_safely():
    result = GCPAdapter(credentials={}).rollback(DeployRun(platform="gcp", metadata={}))
    assert not result.ok
    assert "previous_revision" in result.message


# --- GCE -------------------------------------------------------------------


def test_gce_validate_reports_all_missing_inputs():
    result = GCEAdapter(credentials={}).validate(_config(project_ref=""))
    joined = " ".join(result.errors)
    assert not result.ok
    assert "service_account_json" in joined
    assert "zone" in joined
    assert "instance_template" in joined


def test_gce_validate_warns_about_in_place_strategy():
    result = GCEAdapter(credentials={}).validate(_config(extra={"strategy": "in_place"}))
    assert not result.ok  # still missing credentials
    assert any("in_place" in warning for warning in result.warnings)


def test_gce_plan_replace_is_high_risk_but_reversible():
    plan = GCEAdapter(credentials={"zone": "us-central1-a"}).plan(_config(extra={"instance_template": "tmpl"}))
    assert plan.risk is RiskLevel.HIGH
    assert plan.reversible and not plan.destructive
    assert plan.metadata == {"strategy": "replace", "zone": "us-central1-a"}


def test_gce_plan_in_place_is_destructive_and_irreversible():
    plan = GCEAdapter(credentials={"zone": "z"}).plan(_config(extra={"strategy": "in_place"}))
    assert plan.destructive and not plan.reversible


def test_gce_rollback_is_manual_and_never_silently_deletes():
    adapter = GCEAdapter(credentials={})
    assert not adapter.rollback(DeployRun(platform="gce", metadata={})).ok
    guarded = adapter.rollback(DeployRun(platform="gce", external_id="new-1", metadata={"old_instance": "old-1"}))
    assert not guarded.ok
    assert "old-1" in guarded.message and "new-1" in guarded.message


# --- Hugging Face Spaces ---------------------------------------------------


def test_huggingface_validate_reports_all_missing_inputs():
    result = HuggingFaceAdapter(credentials={}).validate(_config(project_ref="", artifact_path="/does/not/exist"))
    joined = " ".join(result.errors)
    assert not result.ok
    assert "hf_token" in joined
    assert "project_ref" in joined
    assert "sdk" in joined
    assert "artifact_path" in joined


def test_huggingface_validate_rejects_unknown_sdk(tmp_path):
    result = HuggingFaceAdapter(credentials={"hf_token": "t"}).validate(
        _config(artifact_path=str(tmp_path), extra={"sdk": "django"})
    )
    assert not result.ok
    assert any("sdk" in error for error in result.errors)


def test_huggingface_plan_counts_files(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "requirements.txt").write_text("gradio")
    plan = HuggingFaceAdapter(credentials={"hf_token": "t"}).plan(
        _config(artifact_path=str(tmp_path), extra={"sdk": "gradio"})
    )
    assert plan.metadata == {"sdk": "gradio", "file_count": 2}
    assert plan.risk is RiskLevel.LOW
    assert plan.reversible and not plan.destructive


def test_huggingface_rollback_requires_target_commit():
    adapter = HuggingFaceAdapter(credentials={"hf_token": "t"})
    assert "rollback_to_commit" in adapter.rollback(DeployRun(platform="huggingface", metadata={})).message
    guarded = adapter.rollback(DeployRun(platform="huggingface", metadata={"rollback_to_commit": "abc123"}))
    assert not guarded.ok
    assert "abc123" in guarded.message


def test_missing_cloud_sdk_raises_actionable_error():
    for adapter_cls, package in ((GCPAdapter, "google-cloud-run"), (GCEAdapter, "google-cloud-compute")):
        try:
            adapter_cls._sdk()
        except RuntimeError as exc:
            assert package in str(exc)
        except ImportError:  # pragma: no cover - _sdk must translate this
            pytest.fail(f"{adapter_cls.__name__}._sdk() leaked ImportError")
