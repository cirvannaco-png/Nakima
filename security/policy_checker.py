import ast
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.policy import RepositoryPolicy


class PolicyChecker:
    def __init__(self, session: AsyncSession, repo_id: int):
        self.session = session
        self.repo_id = repo_id

    async def _get_policy(self) -> RepositoryPolicy | None:
        stmt = select(RepositoryPolicy).where(RepositoryPolicy.repository_id == self.repo_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def check_branch_name(self, branch_name: str) -> bool:
        policy = await self._get_policy()
        if not policy or not policy.branch_pattern:
            return True
        return re.match(policy.branch_pattern, branch_name) is not None

    async def check_required_reviewers(self, pr_data: dict) -> bool:
        policy = await self._get_policy()
        if not policy or not policy.required_reviewers:
            return True
        assigned = [r["login"] for r in pr_data.get("requested_reviewers", [])]
        return all(r in assigned for r in policy.required_reviewers)

    async def check_coding_standards(self, repo_dir: Path, files: list[str]) -> list[str]:
        policy = await self._get_policy()
        if not policy or not policy.require_docstrings:
            return []
        violations = []
        for rel_path in files:
            if not rel_path.endswith(".py"):
                continue
            full_path = repo_dir / rel_path
            if not full_path.exists():
                continue
            missing = self._missing_docstrings(full_path)
            violations.extend(f"Missing docstring: {rel_path}::{name}" for name in missing)
        return violations

    def _missing_docstrings(self, file_path: Path) -> list[str]:
        """Real implementation via the ast module — the original draft
        called self._has_docstrings() but never defined it anywhere."""
        try:
            tree = ast.parse(file_path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            return []

        missing = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if node.name.startswith("_"):
                    continue  # private/dunder — not held to the public docstring bar
                if ast.get_docstring(node) is None:
                    missing.append(node.name)
        return missing

    async def check_license(self, repo_dir: Path) -> bool:
        policy = await self._get_policy()
        if not policy or not policy.require_license:
            return True
        return (repo_dir / "LICENSE").exists() or (repo_dir / "LICENSE.md").exists()

    async def check_all_policies(self, context: dict) -> list[str]:
        """Returns a list of human-readable violations. Empty list = clear to proceed."""
        policy = await self._get_policy()
        violations: list[str] = []
        if not policy:
            return violations

        branch = context.get("branch")
        if branch and not await self.check_branch_name(branch):
            violations.append(f"Branch name '{branch}' does not match required pattern '{policy.branch_pattern}'")

        if context.get("pr_data") and not await self.check_required_reviewers(context["pr_data"]):
            violations.append(f"Missing required reviewers: {policy.required_reviewers}")

        if context.get("repo_dir") and context.get("files"):
            violations.extend(await self.check_coding_standards(Path(context["repo_dir"]), context["files"]))

        if context.get("repo_dir") and not await self.check_license(Path(context["repo_dir"])):
            violations.append("Repository is missing a LICENSE file")

        return violations
