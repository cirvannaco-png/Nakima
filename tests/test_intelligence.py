"""Tests for the Engineering Intelligence Engine: DecisionRegistry and
EventLog. Exercised against a real in-memory async DB (db_session fixture),
not mocked — same convention as tests/test_neis_evolution_service.py.
"""

import uuid

import pytest

from intelligence.decision_registry import DecisionRegistry
from intelligence.event_log import EventLog
from models.repository import Repository


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_decision_registry_records_and_lists(db_session):
    repo = await _make_repo(db_session)
    registry = DecisionRegistry(db_session, repo.id)

    row = await registry.record(
        context="Nakima currently has two graph builders proposed independently.",
        problem="Two parallel knowledge-graph tables would drift out of sync.",
        decision="Reuse models/knowledge.py's KnowledgeNode/KnowledgeEdge for NEIS patterns instead of a new table.",
        justification="Same 'durable fact about this repo' concept; a second table is a bug waiting to happen.",
        alternatives=[{"option": "New models/neis/knowledge_graph.py table", "rejected_because": "duplicates state"}],
        consequences="PatternExtractor writes KnowledgeNode(node_type='pattern') rows.",
        related_files=["models/neis/__init__.py", "neis/analyzers/pattern_extractor.py"],
        author="kelson",
    )

    assert row.id is not None
    assert row.repository_id == repo.id
    assert row.author == "kelson"
    assert row.alternatives[0]["option"].startswith("New models/neis")

    listed = await registry.list_for_repository()
    assert len(listed) == 1
    assert listed[0].id == row.id

    fetched = await registry.get(row.id)
    assert fetched is not None
    assert fetched.decision == row.decision


async def test_decision_registry_is_append_only_ordering(db_session):
    repo = await _make_repo(db_session)
    registry = DecisionRegistry(db_session, repo.id)

    first = await registry.record(
        context="c1", problem="p1", decision="d1", justification="j1"
    )
    second = await registry.record(
        context="c2", problem="p2", decision="d2", justification="j2"
    )

    listed = await registry.list_for_repository()
    # Most recent first.
    assert [row.id for row in listed] == [second.id, first.id]


async def test_event_log_records_a_passed_event(db_session):
    repo = await _make_repo(db_session)
    task_id = uuid.uuid4()
    log = EventLog(db_session, repo.id)

    row = await log.record(
        task_id=task_id,
        task_description="Fix typo in README",
        reason="Issue #12 reported a broken setup link",
        chosen_solution="Corrected the relative link",
        files_modified=["README.md"],
        risk_level="low",
        verification_status="passed",
        tests_executed=["format", "lint", "build", "test", "security"],
    )

    assert row.repository_id == repo.id
    assert row.task_id == task_id
    assert row.verification_status == "passed"
    assert row.tests_executed == ["format", "lint", "build", "test", "security"]

    for_task = await log.list_for_task(task_id)
    assert len(for_task) == 1
    assert for_task[0].id == row.id


async def test_event_log_rejects_invalid_risk_level(db_session):
    repo = await _make_repo(db_session)
    log = EventLog(db_session, repo.id)

    with pytest.raises(ValueError, match="risk_level"):
        await log.record(
            task_description="x",
            reason="x",
            chosen_solution="x",
            risk_level="apocalyptic",
        )


async def test_event_log_rejects_invalid_verification_status(db_session):
    repo = await _make_repo(db_session)
    log = EventLog(db_session, repo.id)

    with pytest.raises(ValueError, match="verification_status"):
        await log.record(
            task_description="x",
            reason="x",
            chosen_solution="x",
            verification_status="vibes",
        )


async def test_event_can_reference_a_decision(db_session):
    repo = await _make_repo(db_session)
    decision = await DecisionRegistry(db_session, repo.id).record(
        context="c", problem="p", decision="d", justification="j"
    )
    row = await EventLog(db_session, repo.id).record(
        decision_id=decision.id,
        task_description="Implement the decision above",
        reason="Follow-through on the recorded decision",
        chosen_solution="Implemented as decided",
    )
    assert row.decision_id == decision.id
