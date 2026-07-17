import uuid
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge import KnowledgeEdge, KnowledgeNode


class KnowledgeGraphBuilder:
    def __init__(self, session: AsyncSession, repo_id: int):
        self.session = session
        self.repo_id = repo_id

    async def index_issue(self, issue_data: Dict) -> KnowledgeNode:
        node = KnowledgeNode(
            id=uuid.uuid4(),  # generated eagerly so it can be referenced before flush
            repository_id=self.repo_id,
            node_type="issue",
            external_id=str(issue_data["number"]),
            summary=issue_data["title"],
            extra_data={"body": issue_data.get("body"), "state": issue_data.get("state")},
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def index_pull_request(self, pr_data: Dict, merged: bool) -> KnowledgeNode:
        node = KnowledgeNode(
            id=uuid.uuid4(),
            repository_id=self.repo_id,
            node_type="pr",
            external_id=str(pr_data["number"]),
            summary=pr_data["title"],
            extra_data={"merged": merged, "state": pr_data.get("state")},
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def link_fix_to_issue(self, fix_commit_sha: str, issue_number: int) -> Optional[KnowledgeEdge]:
        """Links a fix (indexed as a 'commit' knowledge node — call
        index_commit first, or pass an already-indexed sha) to the issue
        it resolves. Returns None (and logs nothing louder than that) if
        either side isn't indexed yet, rather than crashing — this is
        commonly called speculatively from webhook handlers."""
        commit_stmt = select(KnowledgeNode).where(
            KnowledgeNode.repository_id == self.repo_id,
            KnowledgeNode.node_type == "commit",
            KnowledgeNode.external_id == fix_commit_sha,
        )
        issue_stmt = select(KnowledgeNode).where(
            KnowledgeNode.repository_id == self.repo_id,
            KnowledgeNode.node_type == "issue",
            KnowledgeNode.external_id == str(issue_number),
        )
        commit_node = (await self.session.execute(commit_stmt)).scalars().first()
        issue_node = (await self.session.execute(issue_stmt)).scalars().first()
        if not commit_node or not issue_node:
            return None

        edge = KnowledgeEdge(
            id=uuid.uuid4(),
            source_id=commit_node.id,
            target_id=issue_node.id,
            relation="fixes",
        )
        self.session.add(edge)
        await self.session.flush()
        return edge

    async def index_commit(self, sha: str, message: str) -> KnowledgeNode:
        node = KnowledgeNode(
            id=uuid.uuid4(),
            repository_id=self.repo_id,
            node_type="commit",
            external_id=sha,
            summary=message[:500],
            extra_data={},
        )
        self.session.add(node)
        await self.session.flush()
        return node
