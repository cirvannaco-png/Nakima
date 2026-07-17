import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.graph import EdgeType, GraphEdge, GraphNode, NodeType


class GraphQuery:
    """High-level queries over the code graph."""

    def __init__(self, session: AsyncSession, repo_id: int):
        self.session = session
        self.repo_id = repo_id

    async def get_symbol(self, name: str, kind: Optional[NodeType] = None) -> Optional[GraphNode]:
        stmt = select(GraphNode).where(GraphNode.repository_id == self.repo_id, GraphNode.name == name)
        if kind:
            stmt = stmt.where(GraphNode.node_type == kind)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_file_node(self, relative_path: str) -> Optional[GraphNode]:
        """Look up a file node by its actual relative path, not just its
        basename — the original ContextBuilder called get_symbol(name=file_rel)
        for this, but file nodes are indexed by `name` (basename only), so
        any file in a subdirectory would never be found that way."""
        stmt = select(GraphNode).where(
            GraphNode.repository_id == self.repo_id,
            GraphNode.node_type == NodeType.FILE,
            GraphNode.file_path == relative_path,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_callers(self, function_id: uuid.UUID) -> List[GraphNode]:
        stmt = select(GraphNode).join(GraphEdge, GraphEdge.source_id == GraphNode.id).where(
            GraphEdge.target_id == function_id, GraphEdge.edge_type == EdgeType.CALLS
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_callees(self, function_id: uuid.UUID) -> List[GraphNode]:
        stmt = select(GraphNode).join(GraphEdge, GraphEdge.target_id == GraphNode.id).where(
            GraphEdge.source_id == function_id, GraphEdge.edge_type == EdgeType.CALLS
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_tests_for_symbol(self, symbol_id: uuid.UUID) -> List[GraphNode]:
        stmt = (
            select(GraphNode)
            .join(GraphEdge, GraphEdge.source_id == GraphNode.id)
            .where(
                GraphEdge.target_id == symbol_id,
                GraphEdge.edge_type == EdgeType.TESTS,
                GraphNode.node_type == NodeType.TEST,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_dependents(self, file_node_id: uuid.UUID) -> List[GraphNode]:
        """Files that import this file/symbol."""
        stmt = select(GraphNode).join(GraphEdge, GraphEdge.source_id == GraphNode.id).where(
            GraphEdge.target_id == file_node_id, GraphEdge.edge_type == EdgeType.IMPORTS
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_dependencies(self, file_node_id: uuid.UUID) -> List[GraphNode]:
        """Files/symbols this file imports."""
        stmt = select(GraphNode).join(GraphEdge, GraphEdge.target_id == GraphNode.id).where(
            GraphEdge.source_id == file_node_id, GraphEdge.edge_type == EdgeType.IMPORTS
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_contained_symbols(self, container_id: uuid.UUID) -> List[GraphNode]:
        """Symbols directly declared inside a file or class (functions,
        methods, nested classes)."""
        stmt = select(GraphNode).join(GraphEdge, GraphEdge.target_id == GraphNode.id).where(
            GraphEdge.source_id == container_id, GraphEdge.edge_type == EdgeType.CONTAINS
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
