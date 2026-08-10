"""
GCE adapter — real implementation using the official `google-cloud-compute`
client library, implementing the create-and-swap strategy: create a new
instance from a template, wait for the zone operation to finish, then the
caller (or a follow-up call) points traffic at it and decommissions the old
one. No in-place mutation of a running instance by default — that's what
keeps `reversible=True` honest.

NOTE ON VERIFICATION: google-cloud-compute imports and its client classes
construct correctly in this environment. The actual API calls (insert,
zoneOperations.wait, delete) have NOT been exercised against a live GCP
project from this sandbox — compute.googleapis.com isn't reachable here,
and a real call needs a real service account + project anyway. Structurally
correct against the documented SDK surface; verify against a real (ideally
non-production) GCP project before trusting it with real infrastructure.

Real calls used:
  compute_v1.InstancesClient().insert(project, zone, instance_resource)
  compute_v1.ZoneOperationsClient().wait(project, zone, operation)
  compute_v1.InstancesClient().get(project, zone, instance)
  compute_v1.InstancesClient().delete(project, zone, instance)
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger("nakima.deploy_agent.adapters.gce")


class GCEAdapter(DeployAdapter):
    platform = "gce"

    @staticmethod
    def _sdk():
        try:
            from google.cloud import compute_v1
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError(
                "The GCE adapter requires the optional 'google-cloud-compute' and 'google-auth' packages."
            ) from exc
        return compute_v1, service_account

    def _credentials(self):
        import json

        _, service_account = self._sdk()
        sa_info = json.loads(self.credentials["service_account_json"])
        return service_account.Credentials.from_service_account_info(sa_info)

    def validate(self, config: DeployConfig) -> ValidationResult:
        errors, warnings = [], []
        for field_name in ("service_account_json", "project_id", "zone"):
            if field_name not in self.credentials:
                errors.append(f"Missing {field_name} in credentials.")
        if not config.project_ref:
            errors.append("project_ref (instance name) is required.")
        if not config.extra.get("instance_template"):
            errors.append("config.extra['instance_template'] (full resource URL of the source template) is required.")
        strategy = config.extra.get("strategy", "replace")
        if strategy == "in_place":
            warnings.append("strategy='in_place' mutates the live instance directly — no automatic rollback path.")
        if errors:
            return ValidationResult(ok=False, errors=errors, warnings=warnings)

        try:
            compute_v1, _ = self._sdk()
            client = compute_v1.InstancesClient(credentials=self._credentials())
            client.get(
                project=self.credentials["project_id"],
                zone=self.credentials["zone"],
                instance=config.project_ref,
            )
        except Exception as exc:
            # A 404 here is expected/fine for "replace" strategy creating a fresh instance name;
            # anything else (auth, permission) should surface.
            if "404" not in str(exc) and "not found" not in str(exc).lower():
                errors.append(f"GCE API error checking instance: {exc}")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    def plan(self, config: DeployConfig) -> DeployPlan:
        strategy = config.extra.get("strategy", "replace")
        in_place = strategy == "in_place"
        return DeployPlan(
            platform=self.platform,
            summary=f"{'In-place update' if in_place else 'Create-and-swap'} for GCE instance "
            f"'{config.project_ref}' in {self.credentials.get('zone')}",
            changes=(
                [f"Mutate running instance {config.project_ref} directly"]
                if in_place
                else [
                    f"Create new instance from template {config.extra.get('instance_template')}",
                    f"New instance name: {config.project_ref}-{{timestamp}}",
                    "Caller must repoint load balancer/DNS and decommission the old instance "
                    "after health-checking the new one — this adapter does not do that "
                    "automatically, deliberately, since it requires knowing your LB config.",
                ]
            ),
            risk=RiskLevel.HIGH,
            destructive=in_place,
            reversible=not in_place,
            metadata={"strategy": strategy, "zone": self.credentials.get("zone")},
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        import time

        compute_v1, _ = self._sdk()
        project_id = self.credentials["project_id"]
        zone = self.credentials["zone"]
        client = compute_v1.InstancesClient(credentials=self._credentials())

        new_instance_name = f"{config.project_ref}-{int(time.time())}"
        instance_resource = compute_v1.Instance()
        instance_resource.name = new_instance_name
        instance_resource.source_machine_image = config.extra["instance_template"]

        operation = client.insert(project=project_id, zone=zone, instance_resource=instance_resource)

        zone_ops_client = compute_v1.ZoneOperationsClient(credentials=self._credentials())
        zone_ops_client.wait(project=project_id, zone=zone, operation=operation.name)

        logger.info("GCE instance created: %s (operation %s)", new_instance_name, operation.name)
        return DeployRun(
            plan_id=plan.id,
            platform=self.platform,
            external_id=new_instance_name,
            logs_url=f"https://console.cloud.google.com/compute/instancesDetail/zones/{zone}"
            f"/instances/{new_instance_name}?project={project_id}",
            metadata={"zone": zone, "project_id": project_id, "old_instance": config.project_ref},
        )

    def status(self, run: DeployRun) -> DeployStatus:
        compute_v1, _ = self._sdk()
        client = compute_v1.InstancesClient(credentials=self._credentials())
        instance = client.get(project=run.metadata["project_id"], zone=run.metadata["zone"], instance=run.external_id)
        state_map = {
            "PROVISIONING": DeployStatusState.EXECUTING,
            "STAGING": DeployStatusState.EXECUTING,
            "RUNNING": DeployStatusState.LIVE,
            "STOPPING": DeployStatusState.FAILED,
            "TERMINATED": DeployStatusState.FAILED,
        }
        return DeployStatus(
            run_id=run.id,
            state=state_map.get(instance.status, DeployStatusState.PENDING),
            message=instance.status,
        )

    def rollback(self, run: DeployRun) -> RollbackResult:
        old_instance = run.metadata.get("old_instance")
        if not old_instance:
            return RollbackResult(ok=False, message="No prior instance recorded to roll back to.")
        return RollbackResult(
            ok=False,
            message=f"Rollback means repointing traffic back to '{old_instance}' and deleting "
            f"'{run.external_id}' — only safe if '{old_instance}' hasn't already been "
            f"decommissioned. Verify manually before deleting the new instance.",
        )
