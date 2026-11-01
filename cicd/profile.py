"""Portable repository CI configuration with deterministic rendering."""
from __future__ import annotations
import json
from typing import Literal
from pydantic import BaseModel, Field, field_validator
PipelineEngine = Literal["github_actions", "gitlab_ci", "bitbucket_pipelines", "gitea_actions", "generic_git"]
class CICDProfile(BaseModel):
    engine: PipelineEngine = "github_actions"
    language: Literal["python", "node", "go", "generic"] = "python"
    python_version: str = "3.12"
    node_version: str = "22"
    go_version: str = "1.24"
    install_command: str = "pip install -r requirements.txt -r requirements-dev.txt"
    lint_command: str = "ruff check . && ruff format --check ."
    test_command: str = "pytest --tb=short -q"
    build_command: str | None = None
    security_command: str | None = "bandit -r . -x tests -ll"
    branches: list[str] = Field(default_factory=lambda: ["main", "develop"])
    auto_recovery: bool = True
    publish_recovery_pr: bool = False
    deployment_command: str | None = None
    deployment_environment: str = "production"
    require_deployment_approval: bool = True
    @field_validator("branches")
    @classmethod
    def validate_branches(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        if not cleaned or len(cleaned) > 20 or any(len(v) > 100 for v in cleaned):
            raise ValueError("Configure between 1 and 20 valid branch names")
        return cleaned
    @field_validator("install_command", "lint_command", "test_command", "build_command", "security_command", "deployment_command")
    @classmethod
    def validate_command(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 1000 or "\x00" in value:
            raise ValueError("Commands must be 1000 characters or fewer and contain no NUL bytes")
        return value or None
def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)
def _steps(profile: CICDProfile) -> list[tuple[str, str]]:
    steps = [("Install", profile.install_command), ("Lint", profile.lint_command)]
    if profile.build_command:
        steps.append(("Build", profile.build_command))
    steps.append(("Test", profile.test_command))
    if profile.security_command:
        steps.append(("Security scan", profile.security_command))
    return steps
def render_pipeline(profile: CICDProfile) -> dict[str, str]:
    """Render validation CI only. Deployment remains a separately approved action."""
    steps = _steps(profile)
    if profile.engine in ("github_actions", "gitea_actions"):
        lines = ["name: Nakima CI", "on:", "  push:", "    branches:", *[f"      - {_q(b)}" for b in profile.branches], "  pull_request:", "permissions:", "  contents: read", "concurrency:", "  group: ci-" + "${{ github.workflow }}-" + "${{ github.ref }}", "  cancel-in-progress: true", "jobs:", "  validate:", "    runs-on: ubuntu-latest", "    steps:", "      - uses: actions/checkout@v4"]
        if profile.language == "python":
            lines += ["      - uses: actions/setup-python@v5", "        with:", f"          python-version: {_q(profile.python_version)}"]
        elif profile.language == "node":
            lines += ["      - uses: actions/setup-node@v4", "        with:", f"          node-version: {_q(profile.node_version)}"]
        elif profile.language == "go":
            lines += ["      - uses: actions/setup-go@v5", "        with:", f"          go-version: {_q(profile.go_version)}"]
        for label, command in steps:
            lines += [f"      - name: {_q(label)}", "        run: |", *[f"          {line}" for line in command.splitlines()]]
        return {"path": ".github/workflows/nakima-ci.yml", "content": "\n".join(lines) + "\n"}
    if profile.engine == "gitlab_ci":
        lines = ["stages:", "  - validate", "validate:", "  stage: validate", "  image: ubuntu:24.04", "  before_script:", f"    - {_q(profile.install_command)}", "  script:"]
        lines += [f"    - {_q(command)}" for _, command in steps[1:]]
        lines += ["  rules:", '    - if: \'$CI_PIPELINE_SOURCE == "merge_request_event"\'']
        lines += [f"    - if: '$CI_COMMIT_BRANCH == {branch}'" for branch in (_q(b) for b in profile.branches)]
        return {"path": ".gitlab-ci.yml", "content": "\n".join(lines) + "\n"}
    if profile.engine == "bitbucket_pipelines":
        lines = ["image: atlassian/default-image:4", "pipelines:", "  branches:"]
        for branch in profile.branches:
            lines += [f"    {_q(branch)}:", "      - step:", "          name: Nakima validation", "          script:"]
            lines += [f"            - {_q(command)}" for _, command in steps]
        lines += ["  pull-requests:", "    '**':", "      - step:", "          name: Nakima validation", "          script:"]
        lines += [f"            - {_q(command)}" for _, command in steps]
        return {"path": "bitbucket-pipelines.yml", "content": "\n".join(lines) + "\n"}
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "", "# Generated by Nakima. Run from the repository root."]
    for label, command in steps:
        lines += [f"printf '%s\\n' {_q(label)}", command]
    return {"path": ".nakima/ci.sh", "content": "\n".join(lines) + "\n"}
