"""
Supabase adapter — real implementation via the Supabase Management API
(api.supabase.com). Two very different flows depending on config.extra['target']:

  - "migration": POST a raw SQL file's contents to the query endpoint.
    Genuinely destructive and effectively non-reversible from the API alone
    — see the rollback() docstring for why this stays honest about that.
  - "edge_function": PUT the function body to the functions endpoint.
    Ordinary versioned deploy, cheap to redeploy a prior version.

Real endpoints used:
  GET    /v1/projects/{ref}                                  (existence check)
  POST   /v1/projects/{ref}/database/query                    (run migration SQL)
  GET    /v1/projects/{ref}/database/migrations                (migration history, for status)
  PUT    /v1/projects/{ref}/functions/{slug}                    (deploy edge function body)
  GET    /v1/projects/{ref}/functions/{slug}                    (function status)

Credential shape: {"access_token": "..."}
"""

from __future__ import annotations

import logging
import os

import requests

from ..adapter import DeployAdapter
from ..models import (
    DeployConfig, DeployPlan, DeployRun, DeployStatus, DeployStatusState,
    RiskLevel, RollbackResult, ValidationResult,
)

logger = logging.getLogger("nakima.deploy_agent.adapters.supabase")


class SupabaseAdapter(DeployAdapter):
    platform = "supabase"
    BASE_URL = "https://api.supabase.com/v1"

    def _headers(self, content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.credentials.get('access_token', '')}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors, warnings = [], []
        if "access_token" not in self.credentials:
            errors.append("Missing access_token in credentials.")
        target = config.extra.get("target")
        if target not in ("edge_function", "migration"):
            errors.append("config.extra['target'] must be 'edge_function' or 'migration'.")
        if not config.project_ref:
            errors.append("project_ref (Supabase project ref) is required.")
        if not config.artifact_path or not os.path.isfile(config.artifact_path):
            errors.append(f"artifact_path must be an existing file, got: {config.artifact_path!r}")
        if target == "migration" and not config.extra.get("down_migration_path"):
            warnings.append(
                "No down_migration_path provided — this migration will be marked non-reversible."
            )
        if errors:
            return ValidationResult(ok=False, errors=errors, warnings=warnings)

        resp = requests.get(
            f"{self.BASE_URL}/projects/{config.project_ref}", headers=self._headers(), timeout=15
        )
        if resp.status_code == 404:
            errors.append(f"Supabase project not found: {config.project_ref}")
        elif resp.status_code == 401:
            errors.append("Supabase access_token is invalid or expired.")
        else:
            resp.raise_for_status()
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    def plan(self, config: DeployConfig) -> DeployPlan:
        target = config.extra.get("target")
        if target == "migration":
            has_down = bool(config.extra.get("down_migration_path"))
            with open(config.artifact_path) as f:
                sql_preview = f.read(300)
            return DeployPlan(
                platform=self.platform,
                summary=f"Apply migration {config.artifact_path} to Supabase project "
                        f"'{config.project_ref}'",
                changes=[
                    f"Run SQL against live Postgres DB (preview): {sql_preview}...",
                    "No dry-run available from the Management API — this executes directly.",
                ],
                risk=RiskLevel.HIGH,
                destructive=True,
                reversible=has_down,
            )
        return DeployPlan(
            platform=self.platform,
            summary=f"Deploy edge function '{config.project_ref}' body from {config.artifact_path}",
            changes=[f"PUT function body ({os.path.getsize(config.artifact_path)} bytes)"],
            risk=RiskLevel.LOW,
            destructive=False,
            reversible=True,
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        target = config.extra.get("target")
        with open(config.artifact_path, "rb") as f:
            content = f.read()

        if target == "migration":
            resp = requests.post(
                f"{self.BASE_URL}/projects/{config.project_ref}/database/query",
                headers=self._headers(content_type="application/json"),
                json={"query": content.decode("utf-8")},
                timeout=120,
            )
            resp.raise_for_status()
            logger.info("Supabase migration applied to project %s", config.project_ref)
            return DeployRun(
                plan_id=plan.id, platform=self.platform,
                external_id=f"migration-{config.project_ref}",
                metadata={"target": "migration", "project_ref": config.project_ref},
            )

        function_name = config.extra.get("function_name", config.project_ref)
        resp = requests.put(
            f"{self.BASE_URL}/projects/{config.project_ref}/functions/{function_name}",
            headers=self._headers(content_type="application/json"),
            json={"name": function_name, "body": content.decode("utf-8"), "verify_jwt": True},
            timeout=60,
        )
        resp.raise_for_status()
        logger.info("Supabase edge function '%s' deployed", function_name)
        return DeployRun(
            plan_id=plan.id, platform=self.platform,
            external_id=function_name,
            metadata={"target": "edge_function", "project_ref": config.project_ref},
        )

    def status(self, run: DeployRun) -> DeployStatus:
        if run.metadata.get("target") == "migration":
            # Migrations apply synchronously via the query endpoint — by the
            # time execute() returned without raising, it's already live.
            return DeployStatus(run_id=run.id, state=DeployStatusState.LIVE, message="Migration applied")

        project_ref = run.metadata.get("project_ref")
        resp = requests.get(
            f"{self.BASE_URL}/projects/{project_ref}/functions/{run.external_id}",
            headers=self._headers(), timeout=15,
        )
        resp.raise_for_status()
        fn = resp.json()
        status_map = {"ACTIVE": DeployStatusState.LIVE, "REMOVED": DeployStatusState.FAILED}
        return DeployStatus(
            run_id=run.id,
            state=status_map.get(fn.get("status"), DeployStatusState.PENDING),
            message=fn.get("status", ""),
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        if run.metadata.get("target") == "migration":
            return RollbackResult(
                ok=False,
                message="Migration rollback is not automated by design — apply the "
                        "down_migration_path SQL supplied at plan time manually, after "
                        "confirming the current DB state matches expectations.",
            )
        # Edge functions: redeploying a prior version means re-running execute()
        # with that version's artifact — the API has no separate "revert" call.
        return RollbackResult(
            ok=False,
            message="Supabase has no function-revert endpoint — redeploy the previous "
                    "artifact via execute() with the prior version's file.",
        )
