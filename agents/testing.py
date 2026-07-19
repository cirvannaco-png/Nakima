import re
from pathlib import Path
from typing import Any

from agents.base import AgentRequest, AgentResponse, BaseAgent
from execution.sandbox import SandboxExecutor
from utils.file_blocks import apply_file_changes, parse_file_blocks

# pytest-cov's terminal summary line: "TOTAL    120     18    85%"
COVERAGE_TOTAL_RE = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(?P<pct>\d+)%", re.MULTILINE)


class TestingAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "generate_tests":
            return await self.generate_tests(request.context, request.params)
        elif request.action == "measure_coverage":
            return await self.measure_coverage(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def generate_tests(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        repo_dir = Path(context["repo_dir"])
        file_path = repo_dir / params["file"]
        if not file_path.exists():
            return AgentResponse(success=False, error=f"File not found: {params['file']}")

        code = file_path.read_text()
        response = await self.provider.generate_tests(code, {"language": "python", "file": params["file"]})

        # generate_tests() is instructed (via FILE_BLOCK_INSTRUCTIONS) to
        # emit ### FILE: blocks — write_text()ing the raw response would
        # dump those markers into the test file.
        changes = parse_file_blocks(response.content)
        if not changes:
            return AgentResponse(
                success=False,
                error="Provider response did not contain parseable ### FILE: blocks",
                result={"raw_response": response.content},
            )
        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched})

    async def measure_coverage(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        """Runs pytest --cov in the sandbox and parses the real coverage
        percentage out of the output, instead of returning a hardcoded
        placeholder."""
        repo_dir = Path(context["repo_dir"])
        executor = SandboxExecutor()
        result = await executor.run_tests(repo_dir, "pytest --cov --cov-report=term-missing")

        match = COVERAGE_TOTAL_RE.search(result["logs"])
        coverage = float(match.group("pct")) if match else None

        return AgentResponse(
            success=result["success"],
            result={"coverage": coverage, "raw_output": result["logs"][-2000:]},
            error=None if result["success"] else "Test run failed; coverage may be incomplete",
        )
