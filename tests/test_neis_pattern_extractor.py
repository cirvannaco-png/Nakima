from sqlalchemy import select

from models.knowledge import KnowledgeNode
from models.repository import Repository
from neis.analyzers.pattern_extractor import (
    GOD_CLASS_METHOD_THRESHOLD,
    HIGH_COUPLING_FAN_IN_THRESHOLD,
    PatternExtractor,
)
from repository.graph_builder import GraphBuilder


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_extract_returns_empty_when_graph_not_built(db_session):
    repo = await _make_repo(db_session)
    findings = await PatternExtractor(db_session).extract(repo.id)
    assert findings == []


async def test_god_class_detected_above_threshold(db_session, tmp_path):
    methods = "\n".join(f"    def method_{i}(self):\n        pass\n" for i in range(GOD_CLASS_METHOD_THRESHOLD + 1))
    (tmp_path / "big.py").write_text(f"class Everything:\n{methods}")

    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    findings = await PatternExtractor(db_session).extract(repo.id)
    god_classes = [f for f in findings if f["pattern_type"] == "god_class"]
    assert len(god_classes) == 1
    assert god_classes[0]["method_count"] == GOD_CLASS_METHOD_THRESHOLD + 1
    assert "Everything" in god_classes[0]["subject"]


async def test_god_class_not_flagged_below_threshold(db_session, tmp_path):
    (tmp_path / "small.py").write_text(
        "class Fine:\n    def one(self):\n        pass\n\n    def two(self):\n        pass\n"
    )
    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    findings = await PatternExtractor(db_session).extract(repo.id)
    assert [f for f in findings if f["pattern_type"] == "god_class"] == []


async def test_high_coupling_file_detected_above_threshold(db_session, tmp_path):
    (tmp_path / "core.py").write_text("VALUE = 1\n")
    for i in range(HIGH_COUPLING_FAN_IN_THRESHOLD + 1):
        (tmp_path / f"user_{i}.py").write_text("import core\n")

    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    findings = await PatternExtractor(db_session).extract(repo.id)
    coupling = [f for f in findings if f["pattern_type"] == "high_coupling_file"]
    assert len(coupling) == 1
    assert coupling[0]["file_path"] == "core.py"
    assert coupling[0]["fan_in"] == HIGH_COUPLING_FAN_IN_THRESHOLD + 1


async def test_findings_are_persisted_as_knowledge_nodes(db_session, tmp_path):
    methods = "\n".join(f"    def method_{i}(self):\n        pass\n" for i in range(GOD_CLASS_METHOD_THRESHOLD + 1))
    (tmp_path / "big.py").write_text(f"class Everything:\n{methods}")
    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    await PatternExtractor(db_session).extract(repo.id)

    stmt = select(KnowledgeNode).where(KnowledgeNode.repository_id == repo.id, KnowledgeNode.node_type == "pattern")
    nodes = (await db_session.execute(stmt)).scalars().all()
    assert len(nodes) == 1
    assert nodes[0].extra_data["pattern_type"] == "god_class"
