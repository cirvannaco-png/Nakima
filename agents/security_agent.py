import json
from pathlib import Path
from typing import Any

from agents.base import AgentRequest, AgentResponse, BaseAgent
from execution.sandbox import SandboxExecutor


class SecurityAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "scan":
            return await self.scan(request.context, request.params)
        elif request.action == "audit_dependencies":
            return await self.audit_dependencies(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def scan(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        repo_dir = Path(context["repo_dir"])
        file_path = repo_dir / params["file"]
        if not file_path.exists():
            return AgentResponse(success=False, error=f"File not found: {params['file']}")

        code = file_path.read_text()
        analysis = await self.provider.analyze(code, {"focus": "security vulnerabilities and unsafe patterns"})
        return AgentResponse(success=True, result={"file": params["file"], "findings": analysis.content})

    async def audit_dependencies(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        """Runs `safety` against requirements.txt inside the sandbox and
        parses real findings, instead of returning a hardcoded empty list.

        `safety` is already baked into Dockerfile.sandbox, so no runtime
        install is needed. network_disabled=False is passed explicitly here
        (the sandbox defaults to network-disabled for everything else)
        because `safety check` needs to reach the vulnerability feed and,
        unlike build/test/lint, this call never executes anything from the
        (potentially AI-generated) repo — it only reads requirements.txt.
        """
        repo_dir = Path(context["repo_dir"])
        if not (repo_dir / "requirements.txt").exists():
            return AgentResponse(success=True, result={"vulnerabilities": [], "note": "no requirements.txt found"})

        executor = SandboxExecutor()
        result = await executor.run_build(repo_dir, ["safety check --json"], network_disabled=False)

        vulnerabilities = []
        try:
            # safety's --json output is a single top-level JSON array, itself
            # containing nested per-vulnerability arrays (e.g.
            # [["requests", "<2.31.0", "2.0.0", "CVE-..."]]). Using the FIRST
            # "[" (not the last) is required so the whole outer array is
            # captured instead of a truncated inner one.
            json_start = result["logs"].find("[")
            if json_start != -1:
                parsed = json.loads(result["logs"][json_start:])
                vulnerabilities = [{"package": v[0], "installed": v[2], "vulnerability": v[3]} for v in parsed]
        except (json.JSONDecodeError, IndexError):
            pass  # safety found nothing parseable — report the raw log instead of guessing

        return AgentResponse(
            success=True,
            result={"vulnerabilities": vulnerabilities, "raw_output": result["logs"][-2000:]},
        )
