from pathlib import Path
from typing import Any, Dict

from agents.base import AgentRequest, AgentResponse, BaseAgent
from utils.file_blocks import apply_file_changes, parse_file_blocks


class RefactoringAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "refactor_file":
            return await self.refactor_file(request.context, request.params)
        elif request.action == "safe_move":
            return await self.safe_move(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def refactor_file(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        repo_dir = Path(context["repo_dir"])
        file_path = repo_dir / params["file"]
        if not file_path.exists():
            return AgentResponse(success=False, error=f"File not found: {params['file']}")

        code = file_path.read_text()
        instructions = params.get("instructions", "Improve readability and reduce duplication")
        response = await self.provider.refactor(code, instructions, {"file": params["file"]})

        # provider.refactor() is instructed (via FILE_BLOCK_INSTRUCTIONS) to
        # respond in ### FILE: blocks, not raw file content — write_text()ing
        # the raw response directly would put the block markers and any
        # commentary straight into the source file.
        changes = parse_file_blocks(response.content)
        if not changes:
            return AgentResponse(
                success=False,
                error="Provider response did not contain parseable ### FILE: blocks",
                result={"raw_response": response.content},
            )
        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched})

    async def safe_move(self, context: Dict[str, Any], params: Dict[str, Any]) -> AgentResponse:
        """Move a file and ask the provider to rewrite every importer of it.
        `params['importers']` should be a list of relative file paths known
        to import the moved module (e.g. from GraphQuery.get_dependents)."""
        repo_dir = Path(context["repo_dir"])
        src = repo_dir / params["from_path"]
        dst = repo_dir / params["to_path"]
        if not src.exists():
            return AgentResponse(success=False, error=f"Source file not found: {params['from_path']}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        touched = [params["to_path"]]

        importers = params.get("importers", [])
        if importers:
            importer_snippets = "\n\n".join(
                f"### {rel}\n{(repo_dir / rel).read_text()}" for rel in importers if (repo_dir / rel).exists()
            )
            response = await self.provider.generate(
                f"The module at '{params['from_path']}' was moved to '{params['to_path']}'. "
                f"Update every import statement in the files below to point at the new location, "
                f"leaving everything else unchanged.\n\n{importer_snippets}",
                {"repo_dir": str(repo_dir)},
            )
            changes = parse_file_blocks(response.content)
            touched.extend(apply_file_changes(repo_dir, changes))

        return AgentResponse(success=True, result={"moved": True, "files_changed": touched})
