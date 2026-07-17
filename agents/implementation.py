from pathlib import Path
from typing import Any, Dict, List

from agents.base import AgentRequest, AgentResponse, BaseAgent
from repository.engine import RepositoryEngine
from utils.file_blocks import apply_file_changes, parse_file_blocks


class ImplementationAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "generate_changes":
            return await self.generate_changes(request.context, request.params)
        elif request.action == "full_implementation":
            return await self.full_implementation(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def generate_changes(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        """Ask the provider to implement `params['plan']` against the repo at
        context['repo_dir'], parse the response into individual file writes,
        and apply them. Returns the list of touched file paths."""
        repo_dir = Path(context["repo_dir"])
        plan = params["plan"]
        extra_context = params.get("extra_context")

        prompt = f"Implement the following plan:\n{plan}"
        if extra_context:
            snippets = "\n\n".join(
                f"### {s['file']}\n```\n{s['content']}\n```" for s in extra_context.get("code_snippets", [])
            )
            if snippets:
                prompt += f"\n\nRelevant existing code:\n{snippets}"
            dep_graph = extra_context.get("dependency_subgraph")
            if dep_graph:
                prompt += f"\n\nDependency relationships for affected files:\n{dep_graph}"

        response = await self.provider.generate(prompt, {"repo_dir": str(repo_dir)})

        changes = parse_file_blocks(response.content)
        if not changes:
            return AgentResponse(
                success=False,
                error=(
                    "Provider response did not contain any parseable ### FILE: blocks. "
                    "Raw response has been discarded rather than written blindly to disk."
                ),
                result={"raw_response": response.content},
            )

        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched})

    async def full_implementation(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        """Full cycle: clone -> branch -> generate -> commit -> push."""
        engine = RepositoryEngine(context["repo_url"], context.get("github_token"))
        await engine.clone()
        branch = context.get("branch", "nakima/feature")
        await engine.checkout_branch(branch)

        resp = await self.generate_changes({"repo_dir": str(engine.working_dir)}, params)
        if not resp.success:
            return resp

        files_changed: List[str] = resp.result["files_changed"]
        await engine.commit_changes(f"feat: {params.get('title', 'automated change')}", files_changed)
        await engine.push_branch(branch)
        return AgentResponse(success=True, result={"branch": branch, "files_changed": files_changed})
