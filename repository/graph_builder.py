import uuid
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.graph import EdgeType, GraphEdge, GraphNode, NodeType
from repository.analysis import LANG_BY_EXT, RepositoryAnalyzer


class GraphBuilder:
    """Builds and persists the code graph for a repository. Two passes:
    1) create every node (files, classes, functions, methods, imports) and
       index them in a global symbol table by name;
    2) walk import symbols again and connect them to whatever they resolve
       to in that table.

    This is a name-based heuristic, not a real import resolver (no
    handling of aliasing, relative-import resolution, or shadowing) — but
    every edge it produces is generated from a match, not left unresolved.
    """

    def __init__(self, repo_dir: Path, repo_id: int, session: AsyncSession):
        self.repo_dir = Path(repo_dir)
        self.repo_id = repo_id
        self.session = session
        self.analyzer = RepositoryAnalyzer(self.repo_dir)
        # symbol name -> list of (node_id, NodeType)
        self.global_symbols: Dict[str, List[Tuple[str, NodeType]]] = defaultdict(list)
        # relative file path -> file node id
        self.file_nodes: Dict[str, str] = {}

    async def build_full_graph(self) -> nx.DiGraph:
        await self._clear_existing_graph()

        graph = nx.DiGraph()
        self.global_symbols.clear()
        self.file_nodes.clear()

        source_files = [f for f in self.repo_dir.rglob("*") if f.is_file() and f.suffix in LANG_BY_EXT]

        # Pass 1: create nodes for every file and its symbols.
        for file_path in source_files:
            self._create_nodes_for_file(file_path, graph)

        # Pass 2: resolve import dependencies against the symbol table
        # built in pass 1.
        for file_path in source_files:
            self._resolve_dependencies_for_file(file_path, graph)

        await self._persist(graph)
        return graph

    async def _clear_existing_graph(self):
        await self.session.execute(
            GraphEdge.__table__.delete().where(
                GraphEdge.source_id.in_(
                    select(GraphNode.id).where(GraphNode.repository_id == self.repo_id)
                )
            )
        )
        await self.session.execute(
            GraphNode.__table__.delete().where(GraphNode.repository_id == self.repo_id)
        )

    def _create_nodes_for_file(self, file_path: Path, graph: nx.DiGraph):
        rel_path = str(file_path.relative_to(self.repo_dir))

        file_node_id = str(uuid.uuid4())
        graph.add_node(
            file_node_id, id=file_node_id, node_type=NodeType.FILE,
            name=file_path.name, file_path=rel_path,
        )
        self.file_nodes[rel_path] = file_node_id
        self.global_symbols[file_path.stem].append((file_node_id, NodeType.FILE))

        symbols = self.analyzer.extract_symbols(file_path)
        # Track the most recent class node so methods can get a CONTAINS
        # edge from their class, not just the file.
        current_class_id = None
        current_class_end_line = -1

        for sym in symbols:
            if current_class_id and sym["line_start"] > current_class_end_line:
                current_class_id = None

            sym_id = str(uuid.uuid4())
            node_type = NodeType(sym["type"])
            graph.add_node(
                sym_id, id=sym_id, node_type=node_type, name=sym["name"],
                file_path=sym["file"], line_start=sym["line_start"], line_end=sym["line_end"],
                properties=sym.get("properties", {}),
            )

            if node_type == NodeType.CLASS:
                current_class_id = sym_id
                current_class_end_line = sym["line_end"]
                graph.add_edge(file_node_id, sym_id, edge_type=EdgeType.CONTAINS)
            elif node_type == NodeType.METHOD and current_class_id:
                graph.add_edge(current_class_id, sym_id, edge_type=EdgeType.CONTAINS)
            else:
                graph.add_edge(file_node_id, sym_id, edge_type=EdgeType.CONTAINS)

            if node_type != NodeType.IMPORT:
                self.global_symbols[sym["name"]].append((sym_id, node_type))

    def _resolve_dependencies_for_file(self, file_path: Path, graph: nx.DiGraph):
        rel_path = str(file_path.relative_to(self.repo_dir))
        file_node_id = self.file_nodes.get(rel_path)
        if not file_node_id:
            return

        symbols = self.analyzer.extract_symbols(file_path)
        for sym in symbols:
            if sym["type"] != "import":
                continue
            for dep_name in sym.get("properties", {}).get("dependencies", []):
                # Dotted module paths ("pkg.sub.mod") — try the last
                # component too, since that's usually what a matching file
                # or symbol is actually named.
                candidates = [dep_name, dep_name.split(".")[-1]]
                for candidate in candidates:
                    targets = self.global_symbols.get(candidate)
                    if not targets:
                        continue
                    for target_id, _target_type in targets:
                        if target_id == file_node_id:
                            continue
                        graph.add_edge(file_node_id, target_id, edge_type=EdgeType.IMPORTS)
                    break  # stop after the first candidate that matched something

    async def _persist(self, graph: nx.DiGraph):
        for _node_id, data in graph.nodes(data=True):
            self.session.add(GraphNode(
                id=uuid.UUID(data["id"]),
                repository_id=self.repo_id,
                node_type=data["node_type"],
                name=data["name"],
                file_path=data.get("file_path"),
                line_start=data.get("line_start"),
                line_end=data.get("line_end"),
                properties=data.get("properties", {}),
            ))
        for u, v, data in graph.edges(data=True):
            self.session.add(GraphEdge(
                source_id=uuid.UUID(u),
                target_id=uuid.UUID(v),
                edge_type=data["edge_type"],
                properties=data.get("properties", {}),
            ))
        await self.session.commit()
