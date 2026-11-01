from __future__ import annotations

import re
from dataclasses import dataclass

_ALLOWED_PROVIDERS = {"github-actions", "gitlab-ci", "bitbucket-pipelines", "gitea-actions"}
_SAFE_REF = re.compile(r"^[A-Za-z0-9._/*-]{1,100}$")


@dataclass(frozen=True, slots=True)
class CiProfile:
    provider: str
    default_branch: str = "main"
    python_version: str = "3.12"
    run_tests: bool = True
    run_lint: bool = True
    run_security_scan: bool = True

    def validate(self) -> None:
        if self.provider not in _ALLOWED_PROVIDERS:
            raise ValueError("Unsupported CI/CD provider")
        if not _SAFE_REF.fullmatch(self.default_branch) or ".." in self.default_branch:
            raise ValueError("Invalid default branch pattern")
        if self.python_version not in {"3.11", "3.12", "3.13"}:
            raise ValueError("Unsupported Python version")


def render_github_actions(profile: CiProfile) -> str:
    """Render a fixed, non-user-command workflow; review before enabling it."""
    profile.validate()
    if profile.provider not in {"github-actions", "gitea-actions"}:
        raise ValueError("This renderer only supports GitHub/Gitea Actions")
    steps = [
        "      - uses: actions/checkout@v4",
        f"      - uses: actions/setup-python@v5\n        with:\n          python-version: '{profile.python_version}'",
        "      - run: python -m pip install -r requirements.txt",
    ]
    if profile.run_lint:
        steps.append("      - run: ruff check . && ruff format --check .")
    if profile.run_tests:
        steps.append("      - run: pytest --tb=short -q")
    if profile.run_security_scan:
        steps.append("      - run: bandit -r . -ll -x tests,alembic/versions")
    body = "\n".join(steps)
    return (
        "name: Nakima CI\n"
        "on:\n  pull_request:\n  push:\n    branches: ['" + profile.default_branch + "']\n"
        "permissions:\n  contents: read\n"
        "jobs:\n  validate:\n    runs-on: ubuntu-latest\n    steps:\n" + body + "\n"
    )
