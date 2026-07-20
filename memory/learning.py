import logging
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge import KnowledgeEdge, KnowledgeNode
from providers.manager import provider_manager

logger = logging.getLogger(__name__)


class OutcomeAnalyzer:
    def __init__(self, session: AsyncSession, repo_id: int, provider_name: str | None = None):
        self.session = session
        self.repo_id = repo_id
        self.provider = provider_manager.get_provider(provider_name)

    async def record_pr_outcome(
        self, pr_data: dict, accepted: bool, review_comments: list[dict], github_token: str | None = None
    ):
        pr_node = KnowledgeNode(
            id=uuid.uuid4(),
            repository_id=self.repo_id,
            node_type="pr",
            external_id=str(pr_data["number"]),
            summary=pr_data["title"],
            extra_data={"state": "merged" if accepted else "closed", "comments": review_comments},
        )
        self.session.add(pr_node)
        await self.session.flush()

        if accepted and pr_data.get("diff_url") and github_token:
            await self._extract_conventions(pr_data["diff_url"], github_token)

    async def _extract_conventions(self, diff_url: str, github_token: str):
        """Fetch the merged PR's diff and ask the provider to summarize any
        coding conventions it demonstrates (import ordering, docstring
        style, naming, etc.), storing the result as a 'convention'
        knowledge node for future planning context."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    diff_url,
                    headers={"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3.diff"},
                )
                resp.raise_for_status()
                diff_text = resp.text[:8000]  # cap: this goes straight into a prompt
        except Exception as e:
            logger.warning(f"Could not fetch diff from {diff_url}: {e}")
            return

        try:
            analysis = await self.provider.analyze(
                diff_text,
                {
                    "task": "Summarize any coding conventions (naming, structure, style, docstrings, "
                    "import ordering) this diff demonstrates, in 2-3 bullet points. If none are "
                    "evident, say so explicitly."
                },
            )
        except Exception as e:
            logger.warning(f"Provider convention extraction failed: {e}")
            return

        convention_node = KnowledgeNode(
            id=uuid.uuid4(),
            repository_id=self.repo_id,
            node_type="convention",
            summary=analysis.content[:1000],
            extra_data={"source_diff_url": diff_url},
        )
        self.session.add(convention_node)
        await self.session.commit()

    async def update_memory_from_failure(self, build_log: str, fix_applied: str):
        """Store a failure-fix pair for future retrieval via MemoryRetriever."""
        fail_id = uuid.uuid4()
        fix_id = uuid.uuid4()

        fail_node = KnowledgeNode(
            id=fail_id,
            repository_id=self.repo_id,
            node_type="failure",
            summary=build_log[:500],
            extra_data={"full_log": build_log[:8000]},
        )
        fix_node = KnowledgeNode(
            id=fix_id,
            repository_id=self.repo_id,
            node_type="fix",
            summary=fix_applied[:500],
            extra_data={"fix": fix_applied},
        )
        self.session.add_all([fail_node, fix_node])

        # fail_id/fix_id were generated up front specifically so this edge
        # can reference them immediately — with the default=uuid.uuid4 on
        # the model instead, .id would still be None here until flush.
        edge = KnowledgeEdge(id=uuid.uuid4(), source_id=fail_id, target_id=fix_id, relation="fixes")
        self.session.add(edge)
        await self.session.commit()
