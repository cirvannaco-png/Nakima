"""
Unit tests for the DeployAgent orchestrator, its approval gate, and the
Fernet-backed secrets store. No network and no platform SDKs required — the
adapter is a fake implementing the DeployAdapter interface.
"""

import os
import sys

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.adapter import DeployAdapter  # noqa: E402
from deploy_agent.models import (  # noqa: E402
    DeployConfig,
    DeployPlan,
    DeployRun,
    DeployStatus,
    DeployStatusState,
    RiskLevel,
    RollbackResult,
    ValidationResult,
)
from deploy_agent.orchestrator import (  # noqa: E402
    ApprovalRejectedError,
    DeployAgent,
    UnknownPlatformError,
    ValidationFailedError,
)
from deploy_agent.secrets_store import (  # noqa: E402
    CredentialNotFoundError,
    InMemorySecretsBackend,
    MissingMasterKeyError,
    SecretsStore,
    SecretsStoreError,
)


class FakeAdapter(DeployAdapter):
    platform = "fake"

    # Class-level switches so tests can steer behaviour without subclassing.
    valid = True
    warnings: list[str] = []
    risk = RiskLevel.LOW
    destructive = False

    def validate(self, config: DeployConfig) -> ValidationResult:
        if not self.valid:
            return ValidationResult(ok=False, errors=["nope"])
        return ValidationResult(ok=True, warnings=list(self.warnings))

    def plan(self, config: DeployConfig) -> DeployPlan:
        return DeployPlan(
            platform=self.platform,
            summary="fake plan",
            changes=["do the thing"],
            risk=self.risk,
            destructive=self.destructive,
        )

    def execute(self, config: DeployConfig, plan: DeployPlan) -> DeployRun:
        return DeployRun(plan_id=plan.id, platform=self.platform, external_id="ext-1")

    def status(self, run: DeployRun) -> DeployStatus:
        return DeployStatus(run_id=run.id, state=DeployStatusState.LIVE, live_url="https://example.test")

    def rollback(self, run: DeployRun) -> RollbackResult:
        return RollbackResult(ok=True, restored_to="ext-0")


@pytest.fixture
def store():
    s = SecretsStore(InMemorySecretsBackend(), master_key=Fernet.generate_key().decode())
    s.put("fake", "default", {"api_token": "tok"})
    return s


@pytest.fixture
def config():
    return DeployConfig(platform="fake", project_ref="proj", artifact_path="/tmp/artifact")


def _agent(store, approved=True, **kwargs):
    return DeployAgent(
        secrets_store=store,
        adapters={"fake": FakeAdapter},
        approval_callback=lambda plan: approved,
        **kwargs,
    )


# --- secrets store ---------------------------------------------------------


def test_generate_master_key_is_usable():
    key = SecretsStore.generate_master_key()
    SecretsStore(InMemorySecretsBackend(), master_key=key)


def test_missing_master_key_raises(monkeypatch):
    monkeypatch.delenv(SecretsStore.MASTER_KEY_ENV, raising=False)
    with pytest.raises(MissingMasterKeyError):
        SecretsStore(InMemorySecretsBackend())


def test_master_key_from_env(monkeypatch):
    monkeypatch.setenv(SecretsStore.MASTER_KEY_ENV, Fernet.generate_key().decode())
    store = SecretsStore(InMemorySecretsBackend())
    store.put("vercel", "prod", {"api_token": "abc"})
    assert store.get("vercel", "prod") == {"api_token": "abc"}


def test_values_are_encrypted_at_rest():
    backend = InMemorySecretsBackend()
    store = SecretsStore(backend, master_key=Fernet.generate_key().decode())
    store.put("vercel", "prod", {"api_token": "super-secret"})
    record = backend.load("vercel", "prod")
    assert b"super-secret" not in record.encrypted_value
    assert record.last_used_at is None
    store.get("vercel", "prod")
    assert backend.load("vercel", "prod").last_used_at is not None


def test_get_missing_credential_raises():
    store = SecretsStore(InMemorySecretsBackend(), master_key=Fernet.generate_key().decode())
    with pytest.raises(CredentialNotFoundError):
        store.get("vercel", "prod")


def test_wrong_master_key_raises_store_error():
    backend = InMemorySecretsBackend()
    SecretsStore(backend, master_key=Fernet.generate_key().decode()).put("vercel", "prod", {"a": "b"})
    other = SecretsStore(backend, master_key=Fernet.generate_key().decode())
    with pytest.raises(SecretsStoreError):
        other.get("vercel", "prod")


def test_delete_removes_credential():
    store = SecretsStore(InMemorySecretsBackend(), master_key=Fernet.generate_key().decode())
    store.put("vercel", "prod", {"a": "b"})
    store.delete("vercel", "prod")
    with pytest.raises(CredentialNotFoundError):
        store.get("vercel", "prod")


def test_backend_interface_is_abstract_by_contract():
    from deploy_agent.secrets_store import SecretsBackend, StoredCredential

    backend = SecretsBackend()
    cred = StoredCredential(platform="p", label="l", encrypted_value=b"x")
    for call in (
        lambda: backend.save(cred),
        lambda: backend.load("p", "l"),
        lambda: backend.mark_used("p", "l"),
        lambda: backend.delete("p", "l"),
    ):
        with pytest.raises(NotImplementedError):
            call()


# --- orchestrator ----------------------------------------------------------


def test_run_happy_path(store, config):
    status = _agent(store).run(config)
    assert status.state is DeployStatusState.LIVE
    assert status.live_url == "https://example.test"


def test_unknown_platform_raises(store):
    agent = _agent(store)
    with pytest.raises(UnknownPlatformError):
        agent.run(DeployConfig(platform="nope", project_ref="p", artifact_path="/tmp/a"))


def test_validation_failure_raises(store, config, monkeypatch):
    monkeypatch.setattr(FakeAdapter, "valid", False)
    with pytest.raises(ValidationFailedError) as exc:
        _agent(store).run(config)
    assert exc.value.result.errors == ["nope"]


def test_validation_warnings_do_not_block(store, config, monkeypatch):
    monkeypatch.setattr(FakeAdapter, "warnings", ["heads up"])
    assert _agent(store).run(config).state is DeployStatusState.LIVE


def test_rejected_approval_raises(store, config):
    with pytest.raises(ApprovalRejectedError):
        _agent(store, approved=False).run(config)


def test_auto_approve_low_risk_skips_gate(store, config):
    def deny(plan):  # pragma: no cover - must never be called
        raise AssertionError("approval gate should have been skipped")

    agent = DeployAgent(
        secrets_store=store,
        adapters={"fake": FakeAdapter},
        approval_callback=deny,
        auto_approve_low_risk=True,
    )
    assert agent.run(config).state is DeployStatusState.LIVE


def test_auto_approve_does_not_apply_to_destructive_plans(store, config, monkeypatch):
    monkeypatch.setattr(FakeAdapter, "destructive", True)
    agent = DeployAgent(
        secrets_store=store,
        adapters={"fake": FakeAdapter},
        approval_callback=lambda plan: False,
        auto_approve_low_risk=True,
    )
    with pytest.raises(ApprovalRejectedError):
        agent.run(config)


def test_auto_approve_does_not_apply_to_high_risk_plans(store, config, monkeypatch):
    monkeypatch.setattr(FakeAdapter, "risk", RiskLevel.HIGH)
    agent = DeployAgent(
        secrets_store=store,
        adapters={"fake": FakeAdapter},
        approval_callback=lambda plan: False,
        auto_approve_low_risk=True,
    )
    with pytest.raises(ApprovalRejectedError):
        agent.run(config)


def test_poll_and_rollback(store):
    agent = _agent(store)
    run = DeployRun(platform="fake", external_id="ext-1")
    assert agent.poll("fake", run).state is DeployStatusState.LIVE
    result = agent.rollback("fake", run)
    assert result.ok and result.restored_to == "ext-0"


def test_base_adapter_methods_are_not_implemented():
    class Bare(DeployAdapter):
        platform = "bare"

        def validate(self, config):
            return super().validate(config)

        def plan(self, config):
            return super().plan(config)

        def execute(self, config, plan):
            return super().execute(config, plan)

        def status(self, run):
            return super().status(run)

        def rollback(self, run):
            return super().rollback(run)

    bare = Bare(credentials={})
    cfg = DeployConfig(platform="bare", project_ref="p", artifact_path="/tmp/a")
    for call in (
        lambda: bare.validate(cfg),
        lambda: bare.plan(cfg),
        lambda: bare.execute(cfg, DeployPlan()),
        lambda: bare.status(DeployRun()),
        lambda: bare.rollback(DeployRun()),
    ):
        with pytest.raises(NotImplementedError):
            call()
