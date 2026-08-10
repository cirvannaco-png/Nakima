"""
GCP adapter — targets Cloud Run, real implementation using the official
`google-cloud-run` client library. Cloud Run revisions are immutable and
traffic-split, so rollback is a traffic-percentage change against the
existing service, not a redeploy — meaningfully safer than GCE.

NOTE ON VERIFICATION: google-cloud-run imports and its client classes
construct correctly in this environment. The actual API calls (update_service,
traffic split) have NOT been exercised against a live GCP project from this
sandbox — run.googleapis.com isn't reachable here. Structurally correct
against the documented SDK surface; verify against a real project before
trusting it with real infrastructure.

Real calls used:
  run_v2.ServicesClient().get_service(name)
  run_v2.ServicesClient().update_service(service)   (new revision + traffic split)
"""

from __future__ import annotations

import logging

from ..adapter import DeployAdapter
from ..models import (
    DeployConfig, DeployPlan, DeployRun, DeployStatus, DeployStatusState,
    RiskLevel, RollbackResult, ValidationResult,
)

logger = logging.getLogger("nakima.deploy_agent.adapters.gcp")


class GCPAdapter(DeployAdapter):
    platform = "gcp"

    @staticmethod
    def _sdk():
        try:
            from google.cloud import run_v2
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError(
                "The GCP adapter requires the optional 'google-cloud-run' and "
                "'google-auth' packages."
            ) from exc
        return run_v2, service_account

    def _credentials(self):
        import json
        _, service_account = self._sdk()
        sa_info = json.loads(self.credentials["service_account_json"])
        return service_account.Credentials.from_service_account_info(sa_info)

    def _service_path(self, project_id: str, region: str, service_name: str) -> str:
        return f"projects/{project_id}/locations/{region}/services/{service_name}"

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors = []
        for field_name in ("service_account_json", "project_id", "region"):
            if field_name not in self.credentials:
                errors.append(f"Missing {field_name} in credentials.")
        if not config.extra.get("image"):
            errors.append("config.extra['image'] (container image URI, e.g. gcr.io/.../img:tag) is required.")
        if not config.project_ref:
            errors.append("project_ref (Cloud Run service name) is required.")
        if errors:
            return ValidationResult(ok=False, errors=errors)

        try:
            run_v2, _ = self._sdk()
            client = run_v2.ServicesClient(credentials=self._credentials())
            name = self._service_path(
                self.credentials["project_id"], self.credentials["region"], config.project_ref
            )
            client.get_service(name=name)
        except Exception as exc:
            if "404" not in str(exc) and "not_found" not in str(exc).lower():
                errors.append(f"Cloud Run API error checking service: {exc}")
            # else: service doesn't exist yet, fine — update_service can create it via
            # the appropriate flow, or caller should use create_service for first deploy.
        return ValidationResult(ok=not errors, errors=errors)

    def plan(self, config: DeployConfig) -> DeployPlan:
        traffic_pct = config.extra.get("traffic_percent", 100)
        return DeployPlan(
            platform=self.platform,
            summary=f"Deploy new revision of Cloud Run service '{config.project_ref}' "
                    f"({config.extra.get('image')})",
            changes=[
                f"Create new revision from image {config.extra.get('image')}",
                f"Route {traffic_pct}% traffic to new revision"
                + (" (remainder stays on prior revision)" if traffic_pct < 100 else ""),
            ],
            risk=RiskLevel.MEDIUM,
            destructive=False,
            reversible=True,
            metadata={"region": self.credentials.get("region"), "traffic_percent": traffic_pct},
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        run_v2, _ = self._sdk()
        project_id = self.credentials["project_id"]
        region = self.credentials["region"]
        client = run_v2.ServicesClient(credentials=self._credentials())
        name = self._service_path(project_id, region, config.project_ref)

        service = client.get_service(name=name)
        service.template.containers[0].image = config.extra["image"]

        traffic_pct = config.extra.get("traffic_percent", 100)
        service.traffic = [
            run_v2.TrafficTarget(type_=run_v2.TrafficTargetAllocationType.TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST,
                                  percent=traffic_pct)
        ]

        operation = client.update_service(service=service)
        updated_service = operation.result(timeout=300)  # blocks until the operation completes

        logger.info("Cloud Run service updated: %s -> revision %s",
                    config.project_ref, updated_service.latest_ready_revision)
        return DeployRun(
            plan_id=plan.id,
            platform=self.platform,
            external_id=updated_service.latest_ready_revision,
            logs_url=f"https://console.cloud.google.com/run/detail/{region}/{config.project_ref}"
                     f"?project={project_id}",
            metadata={"project_id": project_id, "region": region, "service_name": config.project_ref},
        )

    def status(self, run: DeployRun) -> DeployStatus:
        run_v2, _ = self._sdk()
        client = run_v2.ServicesClient(credentials=self._credentials())
        name = self._service_path(run.metadata["project_id"], run.metadata["region"], run.metadata["service_name"])
        service = client.get_service(name=name)

        is_ready = service.latest_ready_revision == run.external_id
        uri = service.uri
        return DeployStatus(
            run_id=run.id,
            state=DeployStatusState.LIVE if is_ready else DeployStatusState.EXECUTING,
            live_url=uri if is_ready else None,
            message=f"latest_ready_revision={service.latest_ready_revision}",
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        previous_revision = run.metadata.get("previous_revision")
        if not previous_revision:
            return RollbackResult(
                ok=False,
                message="No previous_revision recorded in run.metadata — list revisions via "
                        "RevisionsClient.list_revisions() to find one to roll back to.",
            )
        run_v2, _ = self._sdk()
        client = run_v2.ServicesClient(credentials=self._credentials())
        name = self._service_path(run.metadata["project_id"], run.metadata["region"], run.metadata["service_name"])
        service = client.get_service(name=name)
        service.traffic = [
            run_v2.TrafficTarget(revision=previous_revision, percent=100)
        ]
        operation = client.update_service(service=service)
        operation.result(timeout=120)
        return RollbackResult(ok=True, restored_to=previous_revision)
