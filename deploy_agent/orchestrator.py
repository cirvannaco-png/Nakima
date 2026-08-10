"""
DeployAgent: the sixth agent in Nakima's pipeline.

Flow:
  NEIS Decision Engine accepts roadmap item
    -> build/test in Docker sandbox (existing Nakima pipeline)
    -> DeployAgent.run(config)
         validate() -> plan() -> [human approval gate] -> execute() -> poll status()
    -> result reported back through the same roadmap PATCH endpoint pattern
       you already use for accepted items.

The approval gate is a callback, not baked in, so you can wire it to
whatever you already use for the roadmap PATCH / GitHub issue flow
(Slack approval, GitHub issue comment, a CLI prompt, etc.) without
touching this file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .adapter import DeployAdapter
from .models import (
    DeployConfig,
    DeployPlan,
    DeployRun,
    DeployStatus,
    RiskLevel,
    RollbackResult,
    ValidationResult,
)
from .secrets_store import SecretsStore

logger = logging.getLogger("nakima.deploy_agent")

# Signature: (plan: DeployPlan) -> bool   (True = approved)
ApprovalCallback = Callable[[DeployPlan], bool]


class DeployAgentError(Exception):
    pass


class UnknownPlatformError(DeployAgentError):
    pass


class ValidationFailedError(DeployAgentError):
    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__(f"Validation failed: {result.errors}")


class ApprovalRejectedError(DeployAgentError):
    def __init__(self, plan: DeployPlan):
        self.plan = plan
        super().__init__(f"Deploy plan {plan.id} was rejected at the approval gate.")


class DeployAgent:
    def __init__(
        self,
        secrets_store: SecretsStore,
        adapters: dict[str, type[DeployAdapter]],
        approval_callback: ApprovalCallback,
        auto_approve_low_risk: bool = False,
    ):
        """
        `adapters` maps platform name -> adapter class (not instance; the
        agent instantiates with the right decrypted credentials per call).

        `auto_approve_low_risk`: if True, plans with risk=LOW and
        destructive=False skip the human gate. Keep this False until you
        trust the plan() risk classification for a given platform.
        """
        self._secrets = secrets_store
        self._adapters = adapters
        self._approve = approval_callback
        self._auto_approve_low_risk = auto_approve_low_risk

    def _get_adapter(self, platform: str, credential_label: str = "default") -> DeployAdapter:
        adapter_cls = self._adapters.get(platform)
        if adapter_cls is None:
            raise UnknownPlatformError(f"No adapter registered for '{platform}'. Registered: {list(self._adapters)}")
        creds = self._secrets.get(platform, credential_label)
        return adapter_cls(credentials=creds)

    def run(self, config: DeployConfig, credential_label: str = "default") -> DeployStatus:
        """End-to-end: validate -> plan -> gate -> execute -> status.
        Raises on failure at any stage rather than silently degrading —
        deploy failures should always surface loudly."""
        adapter = self._get_adapter(config.platform, credential_label)

        logger.info("Validating deploy: platform=%s project=%s", config.platform, config.project_ref)
        validation = adapter.validate(config)
        if not validation.ok:
            raise ValidationFailedError(validation)
        for warning in validation.warnings:
            logger.warning("Validation warning [%s]: %s", config.platform, warning)

        plan = adapter.plan(config)
        logger.info(
            "Plan ready: platform=%s risk=%s destructive=%s reversible=%s",
            plan.platform,
            plan.risk.value,
            plan.destructive,
            plan.reversible,
        )

        approved = self._should_auto_approve(plan) or self._approve(plan)
        if not approved:
            raise ApprovalRejectedError(plan)

        run = adapter.execute(config, plan)
        logger.info("Deploy started: run_id=%s external_id=%s", run.id, run.external_id)

        status = adapter.status(run)
        logger.info("Deploy status: run_id=%s state=%s", run.id, status.state.value)
        return status

    def _should_auto_approve(self, plan: DeployPlan) -> bool:
        return self._auto_approve_low_risk and plan.risk == RiskLevel.LOW and not plan.destructive

    def poll(self, platform: str, run: DeployRun, credential_label: str = "default") -> DeployStatus:
        adapter = self._get_adapter(platform, credential_label)
        return adapter.status(run)

    def rollback(self, platform: str, run: DeployRun, credential_label: str = "default") -> RollbackResult:
        adapter = self._get_adapter(platform, credential_label)
        logger.warning("Rolling back: platform=%s run_id=%s", platform, run.id)
        return adapter.rollback(run)
