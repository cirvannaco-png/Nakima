"""
Vercel adapter — real implementation. Vercel's deploy API is a two-step
flow, unlike Netlify's single zip PUT:

  1. For each file: PUT /v2/files with the raw file bytes as body and an
     `x-vercel-digest` header (sha1 of the file contents). Vercel dedupes
     by hash — files it already has from a previous deploy don't need
     re-uploading, but this adapter always PUTs (correct, just not the most
     bandwidth-optimal — an easy future optimization is skip-if-unchanged
     using a local hash cache).
  2. POST /v13/deployments with a `files` array of {file: path, sha, size}
     referencing those uploaded blobs by hash, plus project/target.

Real endpoints used:
  PUT    /v2/files                              (upload one file by content hash)
  POST   /v13/deployments                        (create deployment from uploaded files)
  GET    /v13/deployments/{id}                   (poll status)
  POST   /v10/projects/{id}/alias                 (rollback via alias reassignment)

Credential shape: {"api_token": "...", "team_id": "..." (optional)}
"""

from __future__ import annotations

import hashlib
import logging
import os

import requests

from ..adapter import DeployAdapter
from ..models import (
    DeployConfig,
    DeployPlan,
    DeployRun,
    DeployStatus,
    DeployStatusState,
    RiskLevel,
    RollbackResult,
    ValidationResult,
)

logger = logging.getLogger("nakima.deploy_agent.adapters.vercel")


class VercelAdapter(DeployAdapter):
    platform = "vercel"
    BASE_URL = "https://api.vercel.com"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.credentials.get('api_token', '')}"}

    def _team_params(self) -> dict:
        team_id = self.credentials.get("team_id")
        return {"teamId": team_id} if team_id else {}

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors = []
        if "api_token" not in self.credentials:
            errors.append("Missing api_token in credentials.")
        if not config.project_ref:
            errors.append("project_ref (Vercel project name/ID) is required.")
        if not config.artifact_path or not os.path.isdir(config.artifact_path):
            errors.append(f"artifact_path must be an existing directory, got: {config.artifact_path!r}")
        if errors:
            return ValidationResult(ok=False, errors=errors)

        resp = requests.get(
            f"{self.BASE_URL}/v9/projects/{config.project_ref}",
            headers=self._headers(),
            params=self._team_params(),
            timeout=15,
        )
        if resp.status_code == 404:
            return ValidationResult(ok=False, errors=[f"Vercel project not found: {config.project_ref}"])
        if resp.status_code in (401, 403):
            return ValidationResult(ok=False, errors=["Vercel API token is invalid or lacks project access."])
        resp.raise_for_status()
        return ValidationResult(ok=True)

    def plan(self, config: DeployConfig) -> DeployPlan:
        is_prod = config.environment == "production"
        file_count = sum(len(files) for _, _, files in os.walk(config.artifact_path))
        return DeployPlan(
            platform=self.platform,
            summary=f"Deploy {file_count} files to Vercel project '{config.project_ref}' ({config.environment})",
            changes=[
                f"Upload {file_count} files by content hash",
                f"Create new deployment on project {config.project_ref}",
                f"Target: {'production alias' if is_prod else 'preview URL'}",
            ],
            risk=RiskLevel.LOW,
            destructive=False,
            reversible=True,
            metadata={"team_id": self.credentials.get("team_id"), "file_count": file_count},
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        files_manifest = self._upload_files(config.artifact_path)

        payload = {
            "name": config.project_ref,
            "project": config.project_ref,
            "target": "production" if config.environment == "production" else "preview",
            "files": files_manifest,
        }
        resp = requests.post(
            f"{self.BASE_URL}/v13/deployments",
            headers=self._headers(),
            params=self._team_params(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        deployment = resp.json()
        deployment_id = deployment["id"]
        logger.info("Vercel deployment created: %s", deployment_id)

        return DeployRun(
            plan_id=plan.id,
            platform=self.platform,
            external_id=deployment_id,
            logs_url=f"https://vercel.com/deployments/{deployment_id}",
        )

    def status(self, run: DeployRun) -> DeployStatus:
        resp = requests.get(
            f"{self.BASE_URL}/v13/deployments/{run.external_id}",
            headers=self._headers(),
            params=self._team_params(),
            timeout=15,
        )
        resp.raise_for_status()
        deployment = resp.json()
        state_map = {
            "QUEUED": DeployStatusState.PENDING,
            "BUILDING": DeployStatusState.EXECUTING,
            "INITIALIZING": DeployStatusState.EXECUTING,
            "READY": DeployStatusState.LIVE,
            "ERROR": DeployStatusState.FAILED,
            "CANCELED": DeployStatusState.FAILED,
        }
        ready_state = deployment.get("readyState", "QUEUED")
        url = deployment.get("url")
        return DeployStatus(
            run_id=run.id,
            state=state_map.get(ready_state, DeployStatusState.PENDING),
            live_url=f"https://{url}" if url else None,
            message=ready_state,
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        previous_deployment_id = run.metadata.get("rollback_to_deployment_id")
        alias = run.metadata.get("alias")
        if not previous_deployment_id or not alias:
            return RollbackResult(
                ok=False,
                message="Rollback needs run.metadata['rollback_to_deployment_id'] and ['alias'] set — "
                "list prior deployments via GET /v6/deployments to find one.",
            )
        resp = requests.post(
            f"{self.BASE_URL}/v2/aliases",
            headers=self._headers(),
            params=self._team_params(),
            json={"alias": alias, "deploymentId": previous_deployment_id},
            timeout=30,
        )
        if resp.status_code >= 400:
            return RollbackResult(ok=False, message=f"Alias reassignment failed: {resp.status_code} {resp.text[:200]}")
        return RollbackResult(ok=True, restored_to=previous_deployment_id)

    def _upload_files(self, directory: str) -> list[dict]:
        """Upload every file under `directory` by content hash, return the
        manifest Vercel's /v13/deployments endpoint expects."""
        manifest = []
        for root, _, files in os.walk(directory):
            for filename in files:
                filepath = os.path.join(root, filename)
                if os.path.islink(filepath):
                    raise ValueError(f"Refusing to deploy symlinked artifact: {filepath}")
                rel_path = os.path.relpath(filepath, directory)
                with open(filepath, "rb") as f:
                    content = f.read()
                digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()

                resp = requests.put(
                    f"{self.BASE_URL}/v2/files",
                    headers={**self._headers(), "x-vercel-digest": digest},
                    params=self._team_params(),
                    data=content,
                    timeout=60,
                )
                resp.raise_for_status()

                manifest.append({"file": rel_path, "sha": digest, "size": len(content)})
        logger.info("Uploaded %d files to Vercel", len(manifest))
        return manifest
