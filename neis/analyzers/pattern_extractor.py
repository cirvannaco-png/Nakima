"""Detects a handful of structural patterns from the code graph that
repository.graph_builder.GraphBuilder already persists (GraphNode/
GraphEdge), and records each finding as a KnowledgeNode (node_type="pattern")
via memory.knowledge_graph's existing table rather than a new one — see
models/neis/__init__.py for why.

Depends on GraphBuilder having already run for this repository (typically
triggered by POST /api/v1/repositories/{full_name}/index). If no graph
nodes exist yet, extract() returns an empty list rather than raising —
callers (neis/services/evolution_service.py) treat "no patterns found" and
"graph not built yet" as the same degraded-but-not-fatal case.

Two structural signals only, both computed directly from GraphNode/
GraphEdge with no new heuristics beyond what CONTAINS/IMPORTS edges
already encode:

  - god_class: a class containing an unusually large number of methods.
  - high_coupling_file: a file many other files import — a change to it
    has an outsized blast radius.

A third, tests-based signal (which functions/classes lack a linked test)
would need EdgeType.TESTS edges, but GraphBuilder never creates them today
— there's no code path in repository/graph_builder.py that links a test to
what it tests. That's a real gap in the current repo, not something to
paper over here; extract() does not report on test coverage per-symbol,
and repository.health.HealthScorer's file-count-ratio remains the only
test signal NEIS has until that graph edge exists.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from models.knowledge import KnowledgeNode

GOD_CLASS_METHOD_THRESHOLD = 15
HIGH_COUPLING_FAN_IN_THRESHOLD = 8


class PatternExtractor:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def extract(self, repository_id: int) -> list[dict]:
        findings: list[dict] = []
        findings.extend(await self._find_god_classes(repository_id))
        findings.extend(await self._find_high_coupling_files(repository_id))

        for finding in findings:
            self.session.add(
                KnowledgeNode(
                    id=uuid.uuid4(),
                    repository_id=repository_id,
                    node_type="pattern",
                    external_id=finding["subject"],
                    summary=finding["summary"],
                    extra_data=finding,
                )
            )
        if findings:
            await self.session.flush()
        return findings

    async def _find_god_classes(self, repository_id: int) -> list[dict]:
        method_counts = (
            select(GraphEdge.source_id, func.count(GraphEdge.target_id).label("method_count"))
            .join(GraphNode, GraphNode.id == GraphEdge.target_id)
            .where(GraphEdge.edge_type == EdgeType.CONTAINS, GraphNode.node_type == NodeType.METHOD)
            .group_by(GraphEdge.source_id)
            .having(func.count(GraphEdge.target_id) >= GOD_CLASS_METHOD_THRESHOLD)
        )
        rows = (await self.session.execute(method_counts)).all()
        if not rows:
            return []

        class_ids = [r.source_id for r in rows]
        classes = (await self.session.execute(select(GraphNode).where(GraphNode.id.in_(class_ids)))).scalars().all()
        counts_by_id = {r.source_id: r.method_count for r in rows}

        return [
            {
                "pattern_type": "god_class",
                "subject": f"{c.file_path}::{c.name}",
                "summary": f"Class {c.name} in {c.file_path} has {counts_by_id[c.id]} methods "
                f"(threshold: {GOD_CLASS_METHOD_THRESHOLD}) — a candidate for splitting.",
                "severity": "medium",
                "method_count": counts_by_id[c.id],
                "file_path": c.file_path,
            }
            for c in classes
            if c.repository_id == repository_id
        ]

    async def _find_high_coupling_files(self, repository_id: int) -> list[dict]:
        fan_in = (
            select(GraphEdge.target_id, func.count(GraphEdge.source_id).label("fan_in"))
            .where(GraphEdge.edge_type == EdgeType.IMPORTS)
            .group_by(GraphEdge.target_id)
            .having(func.count(GraphEdge.source_id) >= HIGH_COUPLING_FAN_IN_THRESHOLD)
        )
        rows = (await self.session.execute(fan_in)).all()
        if not rows:
            return []

        target_ids = [r.target_id for r in rows]
        nodes = (
            (
                await self.session.execute(
                    select(GraphNode).where(
                        GraphNode.id.in_(target_ids),
                        GraphNode.repository_id == repository_id,
                        GraphNode.node_type == NodeType.FILE,
                    )
                )
            )
            .scalars()
            .all()
        )
        fan_in_by_id = {r.target_id: r.fan_in for r in rows}

        return [
            {
                "pattern_type": "high_coupling_file",
                "subject": n.file_path or n.name,
                "summary": f"{n.file_path} is imported by {fan_in_by_id[n.id]} other files "
                f"(threshold: {HIGH_COUPLING_FAN_IN_THRESHOLD}) — changes here have wide blast radius.",
                "severity": "medium",
                "fan_in": fan_in_by_id[n.id],
                "file_path": n.file_path,
            }
            for n in nodes
        ]
