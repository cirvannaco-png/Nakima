from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge import KnowledgeEdge, KnowledgeNode


class MemoryRetriever:
    def __init__(self, session: AsyncSession, repo_id: int):
        self.session = session
        self.repo_id = repo_id

    async def get_past_fixes(self, error_signature: str, limit: int = 5) -> List[KnowledgeNode]:
        """Find past fixes for a similar error. The original version
        searched for node_type == "commit", but nothing in the system ever
        indexes a fix that way — OutcomeAnalyzer.update_memory_from_failure
        stores "failure" and "fix" nodes connected by a "fixes" edge. This
        now searches "failure" summaries for a match and follows the edge
        to the fix that resolved it, which is what actually gets written."""
        failure_stmt = select(KnowledgeNode).where(
            KnowledgeNode.repository_id == self.repo_id,
            KnowledgeNode.node_type == "failure",
            KnowledgeNode.summary.ilike(f"%{error_signature}%"),
        ).limit(limit)
        failures = (await self.session.execute(failure_stmt)).scalars().all()
        if not failures:
            return []

        failure_ids = [f.id for f in failures]
        edge_stmt = select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(failure_ids), KnowledgeEdge.relation == "fixes"
        )
        edges = (await self.session.execute(edge_stmt)).scalars().all()
        fix_ids = [e.target_id for e in edges]
        if not fix_ids:
            return []

        fix_stmt = select(KnowledgeNode).where(KnowledgeNode.id.in_(fix_ids))
        return list((await self.session.execute(fix_stmt)).scalars().all())

    async def get_conventions(self, limit: int = 10) -> List[KnowledgeNode]:
        stmt = (
            select(KnowledgeNode)
            .where(KnowledgeNode.repository_id == self.repo_id, KnowledgeNode.node_type == "convention")
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
