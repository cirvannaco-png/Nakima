import json
from pathlib import Path
from typing import Any, Dict

from agents.base import AgentRequest, AgentResponse, BaseAgent
from execution.sandbox import SandboxExecutor


class SecurityAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "scan":
            return await self.scan(request.context, request.params)
        elif request.action == "audit_dependencies":
            return await self.audit_dependencies(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def scan(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        repo_dir = Path(context["repo_dir"])
        file_path = repo_dir / params["file"]
        if not file_path.exists():
            return AgentResponse(success=False, error=f"File not found: {params['file']}")

        code = file_path.read_text()
        analysis = await self.provider.analyze(code, {"focus": "security vulnerabilities and unsafe patterns"})
        return AgentResponse(success=True, result={"file": params["file"], "findings": analysis.content})

    async def audit_dependencies(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        """Runs `safety` against requirements.txt inside the sandbox and
        parses real findings, instead of returning a hardcoded empty list."""
        repo_dir = Path(context["repo_dir"])
        if not (repo_dir / "requirements.txt").exists():
            return AgentResponse(success=True, result={"vulnerabilities": [], "note": "no requirements.txt found"})

        executor = SandboxExecutor()
        result = await executor.run_build(
            repo_dir, ["pip install safety --break-system-packages -q", "safety check --json"]
        )

        vulnerabilities = []
        try:
            # safety's --json output is the last thing printed; the install
            # step's own stdout may precede it in `logs`.
            json_start = result["logs"].rfind("[")
            if json_start != -1:
                parsed = json.loads(result["logs"][json_start:])
                vulnerabilities = [
                    {"package": v[0], "installed": v[2], "vulnerability": v[3]} for v in parsed
                ]
        except (json.JSONDecodeError, IndexError):
            pass  # safety found nothing parseable — report the raw log instead of guessing

        return AgentResponse(
            success=True,
            result={"vulnerabilities": vulnerabilities, "raw_output": result["logs"][-2000:]},
        )
