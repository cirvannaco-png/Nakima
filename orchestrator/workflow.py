import asyncio
import logging
import uuid

from github import Github  # PyGithub — safe now that our local package is githubapp, not github
from sqlalchemy import select

from agents.base import AgentRequest
from agents.debug import DebugAgent
from agents.implementation import ImplementationAgent
from database.session import AsyncSessionLocal
from intelligence.decision_registry import DecisionRegistry
from intelligence.event_log import EventLog
from memory.knowledge_graph import KnowledgeGraphBuilder
from memory.learning import OutcomeAnalyzer
from models.repository import Repository
from models.task import Task, TaskStatus
from neis.reasoning.arbitration_engine import DriftVerdict
from neis.reasoning.decision_engine import DecisionEngine
from planner.context_builder import ContextBuilder
from planner.planner import PlanningEngine
from quality.gate import QualityGate
from repository.analysis import RepositoryAnalyzer
from repository.engine import RepositoryEngine
from repository.graph_builder import GraphBuilder
from security.nsil import SecurityIntelligenceLayer
from security.policy_checker import PolicyChecker
from validation.pipeline import ValidationPipeline

logger = logging.getLogger(__name__)

MAX_VALIDATION_RETRIES = 3


async def run_task(
    task_id: uuid.UUID,
    repo_full_name: str,
    issue_number: int,
    github_token: str | None,
) -> None:
    """Module-level entry point for dashboard-triggered tasks.

    Builds a minimal issue payload so that _run_pipeline can operate
    on the same code path as webhook-triggered tasks.  The issue title
    and body are fetched from GitHub when a token is available; otherwise
    a safe synthetic payload is used so the task can still attempt to run.
    """
    issue_payload: dict = {
        "issue": {
            "number": issue_number,
            "title": f"Issue #{issue_number}",
            "body": None,
        }
    }

    if github_token:
        try:
            from github import Github  # noqa: PLC0415  (local import avoids top-level circular dep)

            gh_issue = Github(github_token).get_repo(repo_full_name).get_issue(issue_number)
            issue_payload = {
                "issue": {
                    "number": gh_issue.number,
                    "title": gh_issue.title,
                    "body": gh_issue.body,
                }
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("run_task: could not fetch issue %s#%s from GitHub: %s", repo_full_name, issue_number, exc)

    orchestrator = WorkflowOrchestrator()
    await orchestrator.process_task(
        task_id=str(task_id),
        repo_full_name=repo_full_name,
        issue_payload=issue_payload,
        github_token=github_token or "",
    )


def security_gate_should_block(nsil_result) -> bool:
    """The Security Gate's actual decision rule, pulled out of
    _run_pipeline so it's testable without mocking the entire pipeline
    (clone/plan/generate/validate/push/PR) just to exercise one if
    statement. Currently: any critical-severity open finding blocks.
    """
    return nsil_result.counts_by_severity.get("critical", 0) > 0


def build_verification_summary(drift_result, nsil_result, quality_result) -> str:
    """Consolidates the outcome of all three gates that ran before this
    point (Intent Drift, Security, Quality) into one line logged as the
    final EngineeringDecision right before a PR is opened — the
    Verification Gate from the spec's four mandatory gates. This is a
    synthesis of decisions already made and separately recorded, not a
    fourth independent check; nothing here can change what already
    happened, since a BLOCK from either earlier gate already returned out
    of _run_pipeline before this function is ever called.
    """
    return (
        f"Intent: {drift_result.verdict.value}; "
        f"Security: {'blocked' if security_gate_should_block(nsil_result) else 'approved'} "
        f"(score {nsil_result.score:.0f}/100, {nsil_result.counts_by_severity.get('critical', 0)} critical); "
        f"Quality: {quality_result.verdict.value}"
        + ("" if quality_result.has_test_changes else " (no test files touched)")
    )


class WorkflowOrchestrator:
    async def handle_webhook_event(self, event_type: str, payload: dict, repo_full_name: str, github_token: str):
        repo = await self._ensure_repository(repo_full_name)

        if event_type == "issues" and payload.get("action") == "opened":
            async with AsyncSessionLocal() as session:
                kg = KnowledgeGraphBuilder(session, repo.id)
                await kg.index_issue(payload["issue"])
                await session.commit()
            await self._handle_new_issue(payload, repo_full_name, github_token)

        elif event_type == "pull_request" and payload.get("action") == "closed":
            await self._handle_pr_closed(payload, repo, github_token)

        elif event_type == "push":
            await self._handle_push(payload, repo, github_token)

        else:
            logger.info(f"No handler for {event_type}/{payload.get('action')}; ignoring")

    async def _ensure_repository(self, repo_full_name: str) -> Repository:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Repository).where(Repository.full_name == repo_full_name))
            repo = result.scalar_one_or_none()
            if not repo:
                repo = Repository(full_name=repo_full_name)
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
            return repo

    async def _handle_new_issue(self, payload: dict, repo_full_name: str, github_token: str):
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

    async def _handle_pr_closed(self, payload: dict, repo: Repository, github_token: str):
        """Learning-system hook: records the PR's outcome and, if merged,
        extracts conventions from the diff for future planning context."""
        pr_data = payload["pull_request"]
        merged = bool(pr_data.get("merged"))

        review_comments: list[dict] = []
        try:
            gh = Github(github_token)
            gh_repo = gh.get_repo(repo.full_name)
            pr = gh_repo.get_pull(pr_data["number"])
            review_comments = [
                {"author": r.user.login if r.user else None, "state": r.state, "body": r.body} for r in pr.get_reviews()
            ]
        except Exception as e:
            logger.warning(f"Could not fetch reviews for PR {pr_data['number']}: {e}")

        async with AsyncSessionLocal() as session:
            kg = KnowledgeGraphBuilder(session, repo.id)
            await kg.index_pull_request(pr_data, merged)

            analyzer = OutcomeAnalyzer(session, repo.id)
            await analyzer.record_pr_outcome(
                pr_data, accepted=merged, review_comments=review_comments, github_token=github_token
            )

    async def _handle_push(self, payload: dict, repo: Repository, github_token: str):
        """Rebuilds the code graph after a push lands, so GraphQuery/
        ContextBuilder reflect the latest state on the next task."""
        try:
            engine = RepositoryEngine(f"https://github.com/{repo.full_name}.git", github_token)
            await engine.clone()
            async with AsyncSessionLocal() as session:
                builder = GraphBuilder(engine.working_dir, repo.id, session)
                graph = await builder.build_full_graph()
                logger.info(f"Rebuilt graph for {repo.full_name}: {graph.number_of_nodes()} nodes")
        except Exception:
            logger.exception(f"Graph rebuild failed for {repo.full_name}")

    async def process_task(self, task_id: str, repo_full_name: str, issue_payload: dict, github_token: str):
        async with AsyncSessionLocal() as session:
            task = await session.get(Task, uuid.UUID(task_id))
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

    async def _run_pipeline(self, task_id: str, repo_full_name: str, issue_payload: dict, github_token: str):
        issue = issue_payload["issue"]
        repo = await self._ensure_repository(repo_full_name)
        repo_url = f"https://github.com/{repo_full_name}.git"

        # 1. Clone + branch (before planning, so the planner works from
        # real repo content instead of nothing)
        engine = RepositoryEngine(repo_url, github_token)
        await engine.clone()
        branch = f"nakima/issue-{task_id[:8]}"
        await engine.checkout_branch(branch)

        analyzer = RepositoryAnalyzer(engine.working_dir)
        structure_summary = analyzer.extract_structure_summary()

        # 2. Plan, grounded in the real repo structure
        planner = PlanningEngine()
        plan = await planner.create_plan(
            requirement=issue.get("body") or issue["title"],
            repo_context={"repo": repo_full_name, "structure_summary": structure_summary},
        )

        # 3. Rebuild the code graph, then pull richer context (real code
        # snippets + dependency subgraph) for the files the plan says
        # it'll touch.
        async with AsyncSessionLocal() as session:
            graph_builder = GraphBuilder(engine.working_dir, repo.id, session)
            await graph_builder.build_full_graph()

            context_builder = ContextBuilder(session, repo.id)
            enriched_context = await context_builder.build_for_task(
                requirement=plan["requirement"],
                affected_files=plan["affected_files"],
                repo_dir=engine.working_dir,
            )

        # 3.5. Intent Drift Validation — NEIS's Decision Engine judges the
        # plan against the latest ProjectRealityModel and stated UserIntent
        # before any code exists, per the Engineering Reasoner principle:
        # checks happen before implementation, not after.
        proposed_change = {
            "title": issue["title"],
            "description": plan["requirement"],
            "affected_files": plan["affected_files"],
            "steps": plan["steps"],
        }
        async with AsyncSessionLocal() as session:
            drift_result = await DecisionEngine(session, repo.id).validate(proposed_change)
            await DecisionRegistry(session, repo.id).record(
                context=f"Intent drift validation for issue #{issue['number']}: {issue['title']}",
                problem=plan["requirement"],
                decision=f"Verdict: {drift_result.verdict.value}",
                justification="; ".join(drift_result.reasoning),
                related_files=plan["affected_files"],
                related_issues=[str(issue["number"])],
            )

        if drift_result.verdict == DriftVerdict.BLOCK:
            await self._fail_task(task_id, f"Blocked by Intent Drift Validator: {'; '.join(drift_result.reasoning)}")
            return
        if drift_result.verdict == DriftVerdict.REQUEST_CONFIRMATION:
            # No human-in-the-loop resume flow exists yet — that needs a new
            # TaskStatus plus a confirmation endpoint, which is a real gap,
            # not something to silently paper over by treating this the
            # same as an ordinary failure. Flagged distinctly in the error
            # so it's greppable and so a maintainer knows to re-file once
            # UserIntent is filled in, rather than assuming the plan itself
            # was rejected.
            await self._fail_task(
                task_id,
                "NEEDS_CONFIRMATION: "
                + "; ".join(drift_result.reasoning)
                + " — automatic confirmation flow is not implemented yet; set or refresh UserIntent "
                "for this repository and re-open the issue.",
            )
            return
        # WARN and APPROVE both proceed — WARN's reasoning is already
        # captured in the EngineeringDecision recorded above.

        # 4. Generate changes
        impl_agent = ImplementationAgent()
        impl_result = await impl_agent.execute(
            AgentRequest(
                action="generate_changes",
                context={"repo_dir": str(engine.working_dir)},
                params={"plan": plan["steps"], "extra_context": enriched_context},
            )
        )
        if not impl_result.success:
            await self._fail_task(task_id, impl_result.error or "code generation failed")
            return
        changed_files = impl_result.result["files_changed"]

        # 5. Validate, with graph-aware debug-and-retry on failure
        validation = ValidationPipeline()
        debug_agent = DebugAgent()
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            validation_result = await validation.validate(engine.working_dir, language="python")
            if validation_result["success"]:
                break
            if attempt == MAX_VALIDATION_RETRIES:
                await self._fail_task(
                    task_id,
                    f"Validation failed after {MAX_VALIDATION_RETRIES} retries: {validation_result['failures']}",
                )
                return

            async with AsyncSessionLocal() as session:
                for failure in validation_result["failures"]:
                    debug_result = await debug_agent.execute(
                        AgentRequest(
                            action="debug_failure",
                            context={"repo_dir": str(engine.working_dir)},
                            params={
                                "error_log": failure["log"],
                                "repo_dir": str(engine.working_dir),
                                "session": session,
                                "repo_id": repo.id,
                            },
                        )
                    )
                    if debug_result.success:
                        changed_files.extend(debug_result.result.get("files_changed", []))
                        async with AsyncSessionLocal() as learn_session:
                            await OutcomeAnalyzer(learn_session, repo.id).update_memory_from_failure(
                                failure["log"], str(debug_result.result.get("files_changed", []))
                            )

        # 6. Policy check before pushing
        changed_files = sorted(set(changed_files))
        async with AsyncSessionLocal() as session:
            policy_checker = PolicyChecker(session, repo.id)
            violations = await policy_checker.check_all_policies(
                {
                    "branch": branch,
                    "repo_dir": str(engine.working_dir),
                    "files": changed_files,
                }
            )
        if violations:
            await self._fail_task(task_id, f"Policy violations: {'; '.join(violations)}")
            return

        # 6.5. Security Gate — NSIL secret + configuration scan. SAST and
        # dependency vulnerabilities are already a blocking part of step 5
        # above (ValidationPipeline's 'security' stage runs bandit/safety);
        # this covers the two NSIL checks that stage doesn't: hardcoded
        # secrets and Dockerfile/workflow misconfigurations. Findings are
        # persisted the same way an on-demand scan's are, so
        # GET /security/{repo}/findings and the PDF report's Security
        # section reflect every task's changes, not just explicit scans.
        async with AsyncSessionLocal() as session:
            nsil_result = await SecurityIntelligenceLayer(session, repo.id).scan(
                engine.working_dir, include_agent_scanners=False
            )
            await DecisionRegistry(session, repo.id).record(
                context=f"Security Gate for issue #{issue['number']}: {issue['title']}",
                problem="Secret and configuration security scan of the working tree before push.",
                decision=(
                    "Blocked"
                    if security_gate_should_block(nsil_result)
                    else "Approved"
                ),
                justification=(
                    f"Security score {nsil_result.score:.0f}/100; "
                    f"{nsil_result.counts_by_severity.get('critical', 0)} critical, "
                    f"{nsil_result.counts_by_severity.get('high', 0)} high open finding(s); "
                    f"{nsil_result.new_finding_count} new, {nsil_result.resolved_finding_count} resolved this scan."
                ),
                related_files=changed_files,
                related_issues=[str(issue["number"])],
            )

        if security_gate_should_block(nsil_result):
            await self._fail_task(
                task_id,
                f"Blocked by Security Gate: {nsil_result.counts_by_severity['critical']} critical finding(s) — "
                f"see GET /security/{repo_full_name}/findings",
            )
            return
        # High/medium/low findings don't block — they're recorded above
        # and surfaced in the PDF report's Security section, same
        # approve-with-a-recorded-warning posture as Intent Drift's WARN.

        # 6.7. Quality Gate — deterministic test-coverage-touch signal.
        # WARN-only by design (see quality/gate.py for why this doesn't
        # try to guess "the" test file for a given source file); it never
        # blocks, only records, same posture as any other WARN verdict.
        quality_result = QualityGate().evaluate(changed_files)
        async with AsyncSessionLocal() as session:
            await DecisionRegistry(session, repo.id).record(
                context=f"Quality Gate for issue #{issue['number']}: {issue['title']}",
                problem="Test-coverage-touch signal for the changed files.",
                decision=quality_result.verdict.value,
                justification="; ".join(quality_result.reasoning),
                related_files=changed_files,
                related_issues=[str(issue["number"])],
            )

        # 7. Commit + push
        await engine.commit_changes(f"feat: {issue['title']}", changed_files)
        await engine.push_branch(branch)

        # 8. Open PR
        gh = Github(github_token)
        gh_repo = gh.get_repo(repo_full_name)
        pr = gh_repo.create_pull(
            title=issue["title"],
            body=f"Closes #{issue['number']}\n\nAutomated PR by Nakima.\n\n**Plan:**\n{plan['steps']}",
            head=branch,
            base=gh_repo.default_branch,
        )

        async with AsyncSessionLocal() as session:
            task = await session.get(Task, uuid.UUID(task_id))
            task.status = TaskStatus.SUCCESS
            task.pr_url = pr.html_url
            await session.commit()

            await DecisionRegistry(session, repo.id).record(
                context=f"Verification Gate for issue #{issue['number']}: {issue['title']}",
                problem="Final synthesis of Intent, Security, and Quality gate outcomes before PR open.",
                decision=f"PR opened: {pr.html_url}",
                justification=build_verification_summary(drift_result, nsil_result, quality_result),
                related_files=changed_files,
                related_issues=[str(issue["number"])],
            )

            await EventLog(session, repo.id).record(
                task_id=uuid.UUID(task_id),
                task_description=issue["title"],
                reason=issue.get("body") or issue["title"],
                chosen_solution=str(plan["steps"]),
                files_modified=changed_files,
                tests_executed=["format", "lint", "build", "test", "security", "security_gate", "quality_gate"],
                risk_level="low" if len(changed_files) <= 3 else "medium",
                verification_status="passed",
                dependencies_affected=[],
            )
        logger.info(f"Task {task_id}: PR created at {pr.html_url}")

    async def _fail_task(self, task_id: str, error: str):
        async with AsyncSessionLocal() as session:
            task = await session.get(Task, uuid.UUID(task_id))
            if task:
                task.status = TaskStatus.FAILED
                task.error = error
                await session.commit()

                await EventLog(session, task.repository_id).record(
                    task_id=uuid.UUID(task_id),
                    task_description=task.title,
                    reason=task.description or task.title,
                    chosen_solution="none — task failed before a change was landed",
                    risk_level="unknown",
                    verification_status="failed",
                    measured_impact={"error": error},
                )
        logger.error(f"Task {task_id} failed: {error}")
