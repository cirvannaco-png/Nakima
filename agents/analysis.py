from pathlib import Path
from typing import Any

from agents.base import AgentRequest, AgentResponse, BaseAgent
from repository.engine import RepositoryEngine


class AnalysisAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "scan_repository":
            return await self.scan_repository(request.context, request.params)
        elif request.action == "detect_issues":
            return await self.detect_issues(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def scan_repository(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        """Clone (or reuse an already-cloned repo_dir) and analyze up to
        `max_files` source files for bugs, security flaws, and architecture
        issues."""
        max_files = params.get("max_files", 30)
        if "repo_dir" in context:
            repo_dir = Path(context["repo_dir"])
        else:
            engine = RepositoryEngine(context["repo_url"], context.get("github_token"))
            await engine.clone()
            repo_dir = engine.working_dir

        files = list(repo_dir.rglob("*.py"))[:max_files]
        results = []
        for file in files:
            try:
                code = file.read_text()
            except Exception:
                continue
            analysis = await self.provider.analyze(code, {"file": str(file), "language": "python"})
            results.append({"file": str(file.relative_to(repo_dir)), "insights": analysis.content})
        return AgentResponse(success=True, result={"findings": results, "files_scanned": len(results)})

    async def detect_issues(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        """Focused pass for a specific concern (dead code, unused deps,
        technical debt) rather than scan_repository's general analysis."""
        focus = params.get("focus", "dead code and unused dependencies")
        repo_dir = Path(context["repo_dir"])
        max_files = params.get("max_files", 15)

        files = list(repo_dir.rglob("*.py"))[:max_files]
        issues = []
        for file in files:
            try:
                code = file.read_text()
            except Exception:
                continue
            analysis = await self.provider.analyze(code, {"focus": focus})
            issues.append({"file": str(file.relative_to(repo_dir)), "findings": analysis.content})
        return AgentResponse(success=True, result={"issues": issues, "focus": focus})
