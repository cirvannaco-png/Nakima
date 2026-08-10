"""
Netlify adapter — real implementation. Netlify's "deploy a folder" flow is
genuinely simple: zip the artifact directory, PUT it as the deploy body.
No file-hash negotiation step (unlike Vercel), which makes this the easiest
adapter to get fully correct without live testing against Netlify itself.

Real endpoints used:
  POST   /api/v1/sites/{site_id}/deploys       (zip body -> new deploy)
  GET    /api/v1/deploys/{deploy_id}            (poll status)
  POST   /api/v1/sites/{site_id}/deploys/{deploy_id}/restore   (rollback)

Credential shape: {"api_token": "..."}
"""

from __future__ import annotations

import io
import logging
import os
import zipfile

import requests

from ..adapter import DeployAdapter
from ..models import (
    DeployConfig, DeployPlan, DeployRun, DeployStatus, DeployStatusState,
    RiskLevel, RollbackResult, ValidationResult,
)

logger = logging.getLogger("nakima.deploy_agent.adapters.netlify")


class NetlifyAdapter(DeployAdapter):
    platform = "netlify"
    BASE_URL = "https://api.netlify.com/api/v1"

    def _headers(self, content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.credentials.get('api_token', '')}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors = []
        if "api_token" not in self.credentials:
            errors.append("Missing api_token in credentials.")
        if not config.project_ref:
            errors.append("project_ref (Netlify site ID or name) is required.")
        if not config.artifact_path or not os.path.isdir(config.artifact_path):
            errors.append(f"artifact_path must be an existing directory, got: {config.artifact_path!r}")
        if errors:
            return ValidationResult(ok=False, errors=errors)

        # Confirm the site actually exists and this token can see it.
        resp = requests.get(
            f"{self.BASE_URL}/sites/{config.project_ref}", headers=self._headers(), timeout=15
        )
        if resp.status_code == 404:
            return ValidationResult(ok=False, errors=[f"Netlify site not found: {config.project_ref}"])
        if resp.status_code == 401:
            return ValidationResult(ok=False, errors=["Netlify API token is invalid or expired."])
        resp.raise_for_status()
        return ValidationResult(ok=True)

    def plan(self, config: DeployConfig) -> DeployPlan:
        file_count = sum(len(files) for _, _, files in os.walk(config.artifact_path))
        return DeployPlan(
            platform=self.platform,
            summary=f"Zip and deploy {file_count} files from {config.artifact_path} "
                    f"to Netlify site '{config.project_ref}'",
            changes=[f"Create new deploy on site {config.project_ref} ({file_count} files)"],
            risk=RiskLevel.LOW,
            destructive=False,
            reversible=True,
            metadata={"file_count": file_count},
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        zip_buffer = self._zip_directory(config.artifact_path)
        resp = requests.post(
            f"{self.BASE_URL}/sites/{config.project_ref}/deploys",
            headers=self._headers(content_type="application/zip"),
            data=zip_buffer.getvalue(),
            timeout=120,
        )
        resp.raise_for_status()
        deploy = resp.json()
        deploy_id = deploy["id"]
        logger.info("Netlify deploy created: %s", deploy_id)
        return DeployRun(
            plan_id=plan.id,
            platform=self.platform,
            external_id=deploy_id,
            logs_url=f"https://app.netlify.com/sites/{config.project_ref}/deploys/{deploy_id}",
            metadata={"site_id": config.project_ref},
        )

    def status(self, run: DeployRun) -> DeployStatus:
        resp = requests.get(f"{self.BASE_URL}/deploys/{run.external_id}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        deploy = resp.json()
        state_map = {
            "new": DeployStatusState.PENDING,
            "building": DeployStatusState.EXECUTING,
            "uploading": DeployStatusState.EXECUTING,
            "uploaded": DeployStatusState.EXECUTING,
            "processing": DeployStatusState.EXECUTING,
            "ready": DeployStatusState.LIVE,
            "error": DeployStatusState.FAILED,
        }
        return DeployStatus(
            run_id=run.id,
            state=state_map.get(deploy.get("state"), DeployStatusState.PENDING),
            live_url=deploy.get("ssl_url") or deploy.get("url"),
            message=deploy.get("error_message") or deploy.get("state", ""),
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        site_id = run.metadata.get("site_id")
        # Netlify's restore endpoint re-publishes a specific PRIOR deploy_id —
        # the caller needs to supply which one via run.metadata["restore_to_deploy_id"].
        restore_target = run.metadata.get("restore_to_deploy_id")
        if not restore_target:
            return RollbackResult(
                ok=False,
                message="No restore_to_deploy_id in run.metadata — list prior deploys via "
                        "GET /sites/{site_id}/deploys and pick one to restore to.",
            )
        resp = requests.post(
            f"{self.BASE_URL}/sites/{site_id}/deploys/{restore_target}/restore",
            headers=self._headers(), timeout=30,
        )
        if resp.status_code >= 400:
            return RollbackResult(ok=False, message=f"Restore failed: {resp.status_code} {resp.text[:200]}")
        return RollbackResult(ok=True, restored_to=restore_target)

    @staticmethod
    def _zip_directory(directory: str) -> io.BytesIO:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(directory):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    if os.path.islink(filepath):
                        raise ValueError(f"Refusing to deploy symlinked artifact: {filepath}")
                    arcname = os.path.relpath(filepath, directory)
                    zf.write(filepath, arcname)
        buffer.seek(0)
        return buffer
