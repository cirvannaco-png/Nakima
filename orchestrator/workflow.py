import asyncio
import logging
from pathlib import Path
from typing import Dict

from github import Github  # PyGithub — safe now that our local package is githubapp, not github
from sqlalchemy import select  # was missing entirely in the original scaffold — repo lookups would NameError

from agents.debug import DebugAgent
from agents.implementation import ImplementationAgent
from agents.base import AgentRequest
from database.session import AsyncSessionLocal
from models.repository import Repository
from models.task import Task, TaskStatus
from planner.planner import PlanningEngine
from repository.engine import RepositoryEngine
from validation.pipeline import ValidationPipeline

logger = logging.getLogger(__name__)

MAX_VALIDATION_RETRIES = 3


class WorkflowOrchestrator:
    async def handle_webhook_event(
        self, event_type: str, payload: Dict, repo_full_name: str, github_token: str
    ):
        await self._ensure_repository(repo_full_name)

        if event_type == "issues" and payload.get("action") == "opened":
            await self._handle_new_issue(payload, repo_full_name, github_token)
        elif event_type == "pull_request":
            pass  # review-on-PR is a natural next extension; not implemented yet
        elif event_type == "push":
            pass  # push-triggered analysis is a natural next extension; not implemented yet
        else:
            logger.info(f"No handler for {event_type}/{payload.get('action')}; ignoring")

    async def _ensure_repository(self, repo_full_name: str) -> Repository:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Repository).where(Repository.full_name == repo_full_name)
            )
            repo = result.scalar_one_or_none()
            if not repo:
                repo = Repository(full_name=repo_full_name)
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
            return repo

    async def _handle_new_issue(self, payload: Dict, repo_full_name: str, github_token: str):
        issue = payload["issue"]
        repo = await self._ensure_repository(repo_full_name)

        async with AsyncSessionLocal() as session:
            task = Task(
                repository_id=repo.id,
                title=issue["title"],
                description=issue.get("body") or "",
                status=TaskStatus.PENDING,
                event_payload=payload,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            task_id = str(task.id)

        asyncio.create_task(self.process_task(task_id, repo_full_name, payload, github_token))

    async def process_task(
        self, task_id: str, repo_full_name: str, issue_payload: Dict, github_token: str
    ):
        async with AsyncSessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return
            task.status = TaskStatus.IN_PROGRESS
            await session.commit()

        try:
            await self._run_pipeline(task_id, repo_full_name, issue_payload, github_token)
        except Exception as e:
            logger.exception(f"Task {task_id} failed with an unhandled exception")
            await self._fail_task(task_id, str(e))

    async def _run_pipeline(
        self, task_id: str, repo_full_name: str, issue_payload: Dict, github_token: str
    ):
        issue = issue_payload["issue"]
        repo_url = f"https://github.com/{repo_full_name}.git"

        # 1. Plan
        planner = PlanningEngine()
        plan = await planner.create_plan(
            requirement=issue.get("body") or issue["title"],
            repo_context={"repo": repo_full_name},
        )

        # 2. Clone + branch
        engine = RepositoryEngine(repo_url, github_token)
        await engine.clone()
        branch = f"nakima/issue-{task_id[:8]}"
        await engine.checkout_branch(branch)

        # 3. Generate changes
        impl_agent = ImplementationAgent()
        impl_result = await impl_agent.execute(
            AgentRequest(
                action="generate_changes",
                context={"repo_dir": str(engine.working_dir)},
                params={"plan": plan["steps"]},
            )
        )
        if not impl_result.success:
            await self._fail_task(task_id, impl_result.error or "code generation failed")
            return
        changed_files = impl_result.result["files_changed"]

        # 4. Validate, with debug-and-retry on failure
        validation = ValidationPipeline()
        debug_agent = DebugAgent()
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            validation_result = await validation.validate(engine.working_dir, language="python")
            if validation_result["success"]:
                break

            if attempt == MAX_VALIDATION_RETRIES:
                await self._fail_task(
                    task_id,
                    f"Validation failed after {MAX_VALIDATION_RETRIES} retries: "
                    f"{validation_result['failures']}",
                )
                return

            for failure in validation_result["failures"]:
                debug_result = await debug_agent.execute(
                    AgentRequest(
                        action="debug_failure",
                        context={"repo_dir": str(engine.working_dir)},
                        params={"error_log": failure["log"], "repo_dir": str(engine.working_dir)},
                    )
                )
                if debug_result.success:
                    changed_files.extend(debug_result.result.get("files_changed", []))

        # 5. Commit + push
        changed_files = sorted(set(changed_files))
        await engine.commit_changes(f"feat: {issue['title']}", changed_files)
        await engine.push_branch(branch)

        # 6. Open PR
        gh = Github(github_token)
        gh_repo = gh.get_repo(repo_full_name)
        pr = gh_repo.create_pull(
            title=issue["title"],
            body=f"Closes #{issue['number']}\n\nAutomated PR by Nakima.\n\n**Plan:**\n{plan['steps']}",
            head=branch,
            base=gh_repo.default_branch,
        )

        async with AsyncSessionLocal() as session:
            task = await session.get(Task, task_id)
            task.status = TaskStatus.SUCCESS
            task.pr_url = pr.html_url
            await session.commit()
        logger.info(f"Task {task_id}: PR created at {pr.html_url}")

    async def _fail_task(self, task_id: str, error: str):
        async with AsyncSessionLocal() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error = error
                await session.commit()
        logger.error(f"Task {task_id} failed: {error}")
