"""NEIS (Nakima Evolution Intelligence System) persistence models.

Four tables, not five: an earlier draft of this feature (see the
"Post-release audit fixes" section of the top-level README) proposed a
models/neis/knowledge_graph.py duplicating models/knowledge.py's
KnowledgeNode/KnowledgeEdge tables. That's not a NEIS-specific concept —
it's the same "durable fact about this repo" idea the rest of Nakima
already persists there. neis/analyzers/pattern_extractor.py writes its
findings as KnowledgeNode rows (node_type="pattern") instead of a parallel
table, and neis/analyzers/project_modeler.py reads models/graph.py's
GraphNode/GraphEdge directly for structural stats. Two knowledge graphs
for one repo would just be a bug waiting to happen (which one is current?),
not a feature.
"""
