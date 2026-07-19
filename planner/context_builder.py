from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from repository.graph_query import GraphQuery


class ContextBuilder:
    """Selects minimal, high-relevance context from the repository graph
    for the planner: dependency subgraph + actual code snippets for the
    files a task is expected to touch."""

    def __init__(self, session: AsyncSession, repo_id: int):
        self.query = GraphQuery(session, repo_id)
        self.repo_id = repo_id

    async def build_for_task(
        self, requirement: str, affected_files: list[str], repo_dir: Path, max_snippet_chars: int = 2000
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "requirement": requirement,
            "code_snippets": [],
            "dependency_subgraph": {},
        }

        for file_rel in affected_files[:10]:
            full_path = repo_dir / file_rel
            if full_path.exists() and full_path.is_file():
                try:
                    snippet = full_path.read_text()[:max_snippet_chars]
                    context["code_snippets"].append({"file": file_rel, "content": snippet})
                except Exception:
                    pass

            # get_file_node matches on the actual relative path, not just
            # a basename, so this now works for files in subdirectories.
            file_node = await self.query.get_file_node(file_rel)
            if file_node:
                dependents = await self.query.get_dependents(file_node.id)
                dependencies = await self.query.get_dependencies(file_node.id)
                context["dependency_subgraph"][file_rel] = {
                    "depended_on_by": [n.name for n in dependents],
                    "depends_on": [n.name for n in dependencies],
                }

        return context
