from models.repository import Repository
from memory.knowledge_graph import KnowledgeGraphBuilder
from memory.learning import OutcomeAnalyzer
from memory.retriever import MemoryRetriever


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_index_issue(db_session):
    repo = await _make_repo(db_session)
    kg = KnowledgeGraphBuilder(db_session, repo.id)
    node = await kg.index_issue({"number": 42, "title": "Fix null pointer", "body": "crashes", "state": "open"})
    assert node.node_type == "issue"
    assert node.external_id == "42"


async def test_get_past_fixes_finds_stored_fix(db_session):
    # This previously always returned [] — it searched node_type == "commit",
    # but nothing ever creates a "commit" node; fixes are stored as "fix"
    # nodes linked from "failure" nodes via a "fixes" edge.
    repo = await _make_repo(db_session)
    analyzer = OutcomeAnalyzer(db_session, repo.id)
    await analyzer.update_memory_from_failure(
        "AttributeError: NoneType has no attribute foo", "Added null check before accessing foo"
    )

    retriever = MemoryRetriever(db_session, repo.id)
    fixes = await retriever.get_past_fixes("AttributeError")
    assert len(fixes) == 1
    assert "null check" in fixes[0].summary


async def test_get_past_fixes_no_match_returns_empty(db_session):
    repo = await _make_repo(db_session)
    analyzer = OutcomeAnalyzer(db_session, repo.id)
    await analyzer.update_memory_from_failure("AttributeError: whatever", "fixed it")

    retriever = MemoryRetriever(db_session, repo.id)
    assert await retriever.get_past_fixes("CompletelyUnrelatedError") == []
