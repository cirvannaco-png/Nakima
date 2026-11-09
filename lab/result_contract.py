"""Versioned, strict result contract shared by the Lab host and sandbox runner."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


FailureClass = Literal[
    "ci_test_failure",
    "build_failure",
    "dependency_conflict",
    "security_finding",
    "deploy_failure",
    "unknown",
]


class LabDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    failure_class: FailureClass
    root_cause_summary: str = Field(min_length=1, max_length=4000)
    affected_files: list[str] = Field(default_factory=list, max_length=250)
    is_security_relevant: bool = False


class LabRunResult(BaseModel):
    """Only this schema may cross the container boundary as a run result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    commit_sha: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    status: Literal["no_issue_found", "healed", "escalated", "failed"]
    baseline_passed: bool | None = None
    full_test_suite_passed: bool | None = None
    attempts_used: int = Field(default=0, ge=0, le=3)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_mandatory_review: bool = True
    diagnosis: LabDiagnosis | None = None
    selected_diff: str | None = Field(default=None, max_length=1_000_000)
    candidate_count: int = Field(default=0, ge=0, le=100)
    error_code: str | None = Field(default=None, max_length=128)
    error: str | None = Field(default=None, max_length=4000)
    duration_seconds: float = Field(ge=0.0)
