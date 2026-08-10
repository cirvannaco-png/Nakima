"""
Core data models shared by every deploy adapter and the orchestrator.

These are intentionally platform-agnostic. Anything platform-specific
(e.g. a Vercel project ID vs a GCP zone) lives inside `config`/`metadata`
dicts rather than as typed fields, so adding a new platform never requires
touching this file.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class RiskLevel(str, enum.Enum):
    """How much scrutiny the human approval gate should apply."""
    LOW = "low"           # stateless, atomic, instantly revertible (Vercel/Netlify preview)
    MEDIUM = "medium"      # stateless prod, or reversible config change
    HIGH = "high"          # stateful / destructive (DB migration, VM replace, prod cutover)


class DeployStatusState(str, enum.Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    LIVE = "live"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class DeployConfig:
    """What the caller (Nakima NEIS pipeline) hands to the Deploy Agent."""
    platform: str                      # "vercel" | "netlify" | "huggingface" | "gce" | "gcp" | "supabase"
    project_ref: str                   # platform-native project/site/space/instance identifier
    artifact_path: str                 # path to build output / repo ref to deploy
    environment: str = "production"    # "production" | "preview" | "staging"
    roadmap_item_id: Optional[str] = None   # ties back to Nakima's roadmap PATCH endpoint
    extra: dict[str, Any] = field(default_factory=dict)  # platform-specific knobs


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DeployPlan:
    """The 'dry run' output. This is what the human approval gate reviews."""
    id: str = field(default_factory=_new_id)
    platform: str = ""
    summary: str = ""                  # human-readable one-liner
    changes: list[str] = field(default_factory=list)   # bullet list of what will happen
    risk: RiskLevel = RiskLevel.LOW
    destructive: bool = False          # e.g. schema migration, VM replacement, DB reset
    reversible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeployRun:
    id: str = field(default_factory=_new_id)
    plan_id: str = ""
    platform: str = ""
    started_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None
    external_id: Optional[str] = None  # e.g. Vercel deployment ID, GCE operation ID
    logs_url: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeployStatus:
    run_id: str
    state: DeployStatusState
    live_url: Optional[str] = None
    message: str = ""
    updated_at: datetime = field(default_factory=_now)


@dataclass
class RollbackResult:
    ok: bool
    restored_to: Optional[str] = None  # previous deployment/version ID
    message: str = ""
