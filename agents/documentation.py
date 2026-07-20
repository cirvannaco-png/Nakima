from pathlib import Path
from typing import Any

from agents.base import AgentRequest, AgentResponse, BaseAgent
from utils.file_blocks import apply_file_changes, parse_file_blocks


class DocumentationAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "update_readme":
            return await self.update_readme(request.context, request.params)
        elif request.action == "generate_docs":
            return await self.generate_docs(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def update_readme(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        repo_dir = Path(context["repo_dir"])
        readme = repo_dir / "README.md"
        existing = readme.read_text() if readme.exists() else ""

        response = await self.provider.generate(
            f"Update the project README to reflect these changes: {params['changes']}\n\n"
            f"Current README:\n{existing}",
            {"repo_dir": str(repo_dir)},
        )

        # provider.generate() also uses FILE_BLOCK_INSTRUCTIONS — the raw
        # response has ### FILE: markers, not just README prose.
        changes = parse_file_blocks(response.content)
        if not changes:
            return AgentResponse(
                success=False,
                error="Provider response did not contain a parseable ### FILE: block for README.md",
                result={"raw_response": response.content},
            )
        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched})

    async def generate_docs(self, context: dict[str, Any], params: dict[str, Any]) -> AgentResponse:
        """Generate API documentation for a given module (params['file'])."""
        repo_dir = Path(context["repo_dir"])
        file_path = repo_dir / params["file"]
        if not file_path.exists():
            return AgentResponse(success=False, error=f"File not found: {params['file']}")

        code = file_path.read_text()
        response = await self.provider.explain(code, {"purpose": "generate API documentation"})

        docs_dir = repo_dir / "docs"
        docs_dir.mkdir(exist_ok=True)
        doc_file = docs_dir / f"{Path(params['file']).stem}.md"
        doc_file.write_text(response.content)  # explain() returns freeform prose, not FILE-block format
        doc_path = str(doc_file.relative_to(repo_dir))
        # Include doc_path in files_changed so callers (e.g. _run_pipeline)
        # can git-add the generated file and include it in the PR commit.
        return AgentResponse(success=True, result={"doc_file": doc_path, "files_changed": [doc_path]})
