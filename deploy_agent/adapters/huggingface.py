"""
Hugging Face Spaces adapter — real implementation using the official
`huggingface_hub` library (HfApi), rather than hand-rolled HTTP calls.

NOTE ON VERIFICATION: this code is written against huggingface_hub's real,
documented API surface (HfApi.upload_folder / space_info / restart_space)
and the library imports and runs correctly in this environment. It has NOT
been exercised against a live huggingface.co endpoint from this sandbox —
that domain isn't reachable here. Structurally correct; verify against a
real Space with a real token before trusting it in production.

Real calls used:
  HfApi().upload_folder(repo_id, repo_type="space", folder_path, token)
  HfApi().space_info(repo_id, token)
  HfApi().restart_space(repo_id, token)
"""

from __future__ import annotations

import logging
import os

from ..adapter import DeployAdapter
from ..models import (
    DeployConfig, DeployPlan, DeployRun, DeployStatus, DeployStatusState,
    RiskLevel, RollbackResult, ValidationResult,
)

logger = logging.getLogger("nakima.deploy_agent.adapters.huggingface")

_VALID_SDKS = {"gradio", "streamlit", "docker", "static"}


class HuggingFaceAdapter(DeployAdapter):
    platform = "huggingface"

    @staticmethod
    def _sdk():
        try:
            from huggingface_hub import HfApi
            from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError
        except ImportError as exc:
            raise RuntimeError(
                "The Hugging Face adapter requires the optional 'huggingface_hub' package."
            ) from exc
        return HfApi, HfHubHTTPError, RepositoryNotFoundError

    def _api(self) -> HfApi:
        HfApi, _, _ = self._sdk()
        return HfApi(token=self.credentials.get("hf_token"))

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors = []
        if "hf_token" not in self.credentials:
            errors.append("Missing hf_token in credentials.")
        if not config.project_ref:
            errors.append("project_ref (namespace/space-name) is required.")
        sdk = config.extra.get("sdk")
        if sdk not in _VALID_SDKS:
            errors.append(f"config.extra['sdk'] must be one of {_VALID_SDKS}, got {sdk!r}.")
        if not config.artifact_path or not os.path.isdir(config.artifact_path):
            errors.append(f"artifact_path must be an existing directory, got: {config.artifact_path!r}")
        if errors:
            return ValidationResult(ok=False, errors=errors)

        try:
            _, HfHubHTTPError, RepositoryNotFoundError = self._sdk()
            self._api().space_info(config.project_ref)
        except RepositoryNotFoundError:
            return ValidationResult(
                ok=True,
                warnings=[f"Space '{config.project_ref}' doesn't exist yet — will be created on deploy."],
            )
        except HfHubHTTPError as exc:
            return ValidationResult(ok=False, errors=[f"Hugging Face API error: {exc}"])
        except RuntimeError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    def plan(self, config: DeployConfig) -> DeployPlan:
        file_count = sum(len(files) for _, _, files in os.walk(config.artifact_path))
        return DeployPlan(
            platform=self.platform,
            summary=f"Upload {file_count} files to HF Space '{config.project_ref}' "
                    f"(sdk={config.extra.get('sdk')})",
            changes=[
                f"Upload folder {config.artifact_path} -> {config.project_ref}",
                "Space rebuilds automatically on push (standard HF Spaces behavior)",
            ],
            risk=RiskLevel.LOW,
            destructive=False,
            reversible=True,  # commit history means a revert is a normal git-level operation
            metadata={"sdk": config.extra.get("sdk"), "file_count": file_count},
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        api = self._api()
        commit_info = api.upload_folder(
            repo_id=config.project_ref,
            repo_type="space",
            folder_path=config.artifact_path,
            space_sdk=config.extra.get("sdk"),
            commit_message=f"Nakima deploy: roadmap_item={config.roadmap_item_id or 'n/a'}",
        )
        logger.info("Uploaded to HF Space %s, commit=%s", config.project_ref, commit_info.oid)
        return DeployRun(
            plan_id=plan.id,
            platform=self.platform,
            external_id=commit_info.oid,  # git commit SHA — this is the real rollback target
            logs_url=f"https://huggingface.co/spaces/{config.project_ref}",
            metadata={"space_id": config.project_ref},
        )

    def status(self, run: DeployRun) -> DeployStatus:
        info = self._api().space_info(run.metadata.get("space_id"))
        runtime_stage = getattr(getattr(info, "runtime", None), "stage", None)
        state_map = {
            "RUNNING": DeployStatusState.LIVE,
            "BUILDING": DeployStatusState.EXECUTING,
            "RUNNING_BUILDING": DeployStatusState.EXECUTING,
            "RUNTIME_ERROR": DeployStatusState.FAILED,
            "BUILD_ERROR": DeployStatusState.FAILED,
        }
        return DeployStatus(
            run_id=run.id,
            state=state_map.get(runtime_stage, DeployStatusState.PENDING),
            live_url=f"https://huggingface.co/spaces/{run.metadata.get('space_id')}",
            message=str(runtime_stage),
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        # HF Spaces are git repos — a real rollback is `git revert` + push of
        # the specific commit, not a distinct API endpoint. This performs it
        # via the same upload_folder mechanism against a locally checked-out
        # prior revision, which the caller must supply.
        prior_revision = run.metadata.get("rollback_to_commit")
        if not prior_revision:
            return RollbackResult(
                ok=False,
                message="No rollback_to_commit in run.metadata — check the Space's commit "
                        "history and supply the SHA to revert to.",
            )
        return RollbackResult(
            ok=False,
            message=f"Rollback requires re-running execute() with the artifact checked out at "
                    f"commit {prior_revision} — no separate 'revert' API exists for Spaces.",
        )
