"""
The one interface every platform adapter must implement.

Design rule: adapters never touch the approval gate, never decrypt secrets
themselves, and never talk to the Docker sandbox directly. The orchestrator
hands them everything they need already resolved. This keeps adapters thin
and testable in isolation (mock the platform's HTTP client, done).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import DeployConfig, DeployPlan, DeployRun, DeployStatus, RollbackResult, ValidationResult


class DeployAdapter(ABC):
    """Base class for a single deploy target (Vercel, Supabase, GCE, ...)."""

    #: short machine name, must match DeployConfig.platform values used to route to this adapter
    platform: str = "unset"

    def __init__(self, credentials: dict[str, str]):
        """
        `credentials` is already-decrypted, already-scoped to this platform.
        The orchestrator resolves this from the secrets store before construction —
        adapters never touch the secrets store directly.
        """
        self.credentials = credentials

    @abstractmethod
    def validate(self, config: DeployConfig) -> ValidationResult:
        """Cheap, side-effect-free checks: required fields present, artifact exists,
        credentials look well-formed, quota not obviously exceeded."""
        raise NotImplementedError

    @abstractmethod
    def plan(self, config: DeployConfig) -> DeployPlan:
        """Dry run. No side effects on the target platform. Must set
        `risk` / `destructive` / `reversible` honestly — this is what the
        human approval gate sees and decides on."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        """Actually perform the deploy. Runs inside the Docker-isolated executor.
        Must only be called after the plan has been approved."""
        raise NotImplementedError

    @abstractmethod
    def status(self, run: DeployRun) -> DeployStatus:
        """Poll the platform for current state of a previously-started run."""
        raise NotImplementedError

    @abstractmethod
    def rollback(self, run: DeployRun) -> RollbackResult:
        """Best-effort revert to the previous known-good state. Adapters for
        platforms where this isn't cleanly possible (e.g. a GCE VM that was
        destructively replaced) should say so honestly in RollbackResult.message
        rather than pretending to succeed."""
        raise NotImplementedError
