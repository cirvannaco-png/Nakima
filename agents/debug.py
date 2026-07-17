import re
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentRequest, AgentResponse, BaseAgent
from models.graph import NodeType
from repository.analysis import RepositoryAnalyzer
from repository.graph_query import GraphQuery
from utils.file_blocks import apply_file_changes, parse_file_blocks

STACK_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')


class DebugAgent(BaseAgent):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        if request.action == "debug_failure":
            return await self.debug_failure(request.context, request.params)
        elif request.action == "apply_fix":
            return await self.apply_fix(request.context, request.params)
        return AgentResponse(success=False, error=f"Unknown action: {request.action}")

    async def debug_failure(self, context: Dict, params: Dict) -> AgentResponse:
        """Given a validation failure's error log, correlate it to code via
        tree-sitter, optionally enrich with call-graph context (who calls
        the failing function), ask the provider for a fix, and apply it
        directly. Returns the list of files the fix touched.

        Graph enrichment (params['session'] + params['repo_id']) is
        optional — if either is missing, debugging still proceeds with
        tree-sitter scope info alone rather than crashing on a
        self.session/context['repo_id'] that was never actually wired up
        anywhere in the original scaffold."""
        error_log = params.get("error_log", "")
        repo_dir = Path(params["repo_dir"])
        session: Optional[AsyncSession] = params.get("session")
        repo_id: Optional[int] = params.get("repo_id")

        frames = self._parse_python_stack_trace(error_log, repo_dir)
        analyzer = RepositoryAnalyzer(repo_dir)
        graph_query = GraphQuery(session, repo_id) if session and repo_id else None

        enriched = []
        for file, line, func in frames:
            snippet = self._read_file_snippet(repo_dir / file, line)
            scope = analyzer.get_enclosing_scope(file, line)
            entry = {"file": file, "line": line, "function": func, "code": snippet, "scope": scope}

            if graph_query:
                symbol = await graph_query.get_symbol(name=func, kind=NodeType.FUNCTION)
                if not symbol:
                    symbol = await graph_query.get_symbol(name=func, kind=NodeType.METHOD)
                if symbol:
                    callers = await graph_query.get_callers(symbol.id)
                    entry["callers"] = [c.name for c in callers]

            enriched.append(entry)

        context_str = "\n".join(
            f"In {f['file']}:{f['line']} (inside {f['scope']})"
            + (f" — called by: {', '.join(f['callers'])}" if f.get("callers") else "")
            + f"\n```\n{f['code']}\n```"
            for f in enriched
        ) or "(no stack frames could be parsed from the error log)"

        response = await self.provider.debug(error_log, {"code_context": context_str, "frames": enriched})

        changes = parse_file_blocks(response.content)
        if not changes:
            return AgentResponse(
                success=False,
                error="Debug provider response did not contain parseable ### FILE: blocks",
                result={"raw_response": response.content, "frames": enriched},
            )

        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched, "frames": enriched})

    async def apply_fix(self, context: Dict, params: Dict) -> AgentResponse:
        """Apply a previously-generated fix response (in FILE-block format) to disk."""
        repo_dir = Path(context["repo_dir"])
        changes = parse_file_blocks(params["fix_response"])
        if not changes:
            return AgentResponse(success=False, error="No parseable file changes in fix_response")
        touched = apply_file_changes(repo_dir, changes)
        return AgentResponse(success=True, result={"files_changed": touched})

    def _parse_python_stack_trace(self, error_log: str, repo_dir: Path) -> List[tuple[str, int, str]]:
        return [(file, int(line), func) for file, line, func in STACK_FRAME_RE.findall(error_log)]

    def _read_file_snippet(self, file_path: Path, line_num: int, context_lines: int = 5) -> str:
        try:
            lines = file_path.read_text().splitlines()
        except Exception:
            return ""
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return "\n".join(lines[start:end])
