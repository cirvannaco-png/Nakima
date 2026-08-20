"""Tests for core/provenance.py.

Provenance is captured at write time, so these tests exercise the real
tagging helpers and the in-memory store rather than mocking them out.
"""

from core.provenance import (
    ContributorType,
    ProvenanceStore,
    hunk_hash,
    tag_agent_generation,
    tag_human_origin,
    tag_review_decision,
)

DIFF = "@@ -1,2 +1,3 @@\n-old line\n+new line\n"


def _agent_record(repo="cirvannaco-png/Nakima", file_path="api/main.py"):
    return tag_agent_generation(
        repo=repo,
        file_path=file_path,
        diff_text=DIFF,
        agent_name="nakima-implementer",
        model_id="claude-sonnet-4-6",
        issue_ref="#482",
        prompt_ref="plan-step-3",
        lines_added=2,
        lines_removed=1,
    )


def test_hunk_hash_is_stable_and_short():
    assert hunk_hash(DIFF) == hunk_hash(DIFF)
    assert len(hunk_hash(DIFF)) == 16
    assert hunk_hash(DIFF) != hunk_hash(DIFF + "x")


def test_agent_generation_is_tagged_as_ai_with_unknown_acceptance():
    record = _agent_record()

    assert record.contributor_type is ContributorType.AI_AGENT
    assert record.agent_name == "nakima-implementer"
    assert record.model_id == "claude-sonnet-4-6"
    assert record.hunk_hash == hunk_hash(DIFF)
    assert record.accepted_verbatim is None
    assert record.commit_sha is None


def test_to_dict_serializes_contributor_type_as_value():
    data = _agent_record().to_dict()

    assert data["contributor_type"] == "ai_agent"
    assert data["lines_added"] == 2
    assert data["lines_removed"] == 1


def test_git_trailer_contains_provenance_fields():
    record = _agent_record()
    trailer = tag_review_decision(record, human_actor="kelson", edited=False).to_git_trailer()

    assert "Nakima-Contributor: ai_agent" in trailer
    assert "Nakima-Agent: nakima-implementer" in trailer
    assert "Nakima-Model: claude-sonnet-4-6" in trailer
    assert "Nakima-Issue: #482" in trailer
    assert "Nakima-Human: kelson" in trailer
    assert "Nakima-Accepted-Verbatim: true" in trailer


def test_review_edit_reclassifies_and_rehashes():
    record = _agent_record()
    edited_diff = DIFF + "+extra human line\n"

    updated = tag_review_decision(record, human_actor="kelson", edited=True, final_diff_text=edited_diff)

    assert updated.contributor_type is ContributorType.HUMAN_EDITED_AI
    assert updated.accepted_verbatim is False
    assert updated.hunk_hash == hunk_hash(edited_diff)
    assert "Nakima-Accepted-Verbatim: false" in updated.to_git_trailer()


def test_human_origin_is_never_reported_as_ai():
    record = tag_human_origin(
        repo="cirvannaco-png/Nakima",
        file_path="docs/readme.md",
        diff_text=DIFF,
        human_actor="kelson",
        issue_ref="#7",
        lines_added=1,
    )

    assert record.contributor_type is ContributorType.HUMAN
    assert record.accepted_verbatim is True
    assert record.agent_name is None
    assert "Nakima-Model" not in record.to_git_trailer()


def test_store_filters_by_repo_and_commit():
    store = ProvenanceStore()
    mine = _agent_record(repo="cirvannaco-png/Nakima")
    theirs = _agent_record(repo="other/repo")
    store.add(mine)
    store.add(theirs)

    assert store.by_repo("cirvannaco-png/Nakima") == [mine]
    assert store.by_commit("abc123") == []

    store.set_commit_sha(mine.record_id, "abc123")
    assert store.by_commit("abc123") == [mine]


def test_summary_aggregates_by_type_agent_and_human():
    store = ProvenanceStore()
    repo = "cirvannaco-png/Nakima"

    ai = _agent_record(repo=repo, file_path="a.py")
    store.add(ai)

    edited = _agent_record(repo=repo, file_path="b.py")
    store.add(tag_review_decision(edited, human_actor="kelson", edited=True))

    store.add(
        tag_human_origin(
            repo=repo,
            file_path="c.py",
            diff_text="+only human\n",
            human_actor="kelson",
            lines_added=3,
            lines_removed=0,
        )
    )

    summary = store.summary(repo)

    assert summary["repo"] == repo
    assert summary["total_records"] == 3
    assert summary["total_lines_added"] == 2 + 2 + 3
    assert summary["total_lines_removed"] == 2
    assert summary["by_contributor_type"]["ai_agent"]["count"] == 1
    assert summary["by_contributor_type"]["human_edited_ai"]["count"] == 1
    assert summary["by_contributor_type"]["human"]["count"] == 1
    assert summary["by_agent"]["nakima-implementer"] == 2
    assert summary["by_human"]["kelson"] == 2
    assert len(summary["records"]) == 3


def test_export_json_writes_readable_summary(tmp_path):
    import json

    store = ProvenanceStore()
    store.add(_agent_record())
    out = tmp_path / "provenance.json"

    store.export_json("cirvannaco-png/Nakima", str(out))

    data = json.loads(out.read_text())
    assert data["total_records"] == 1
    assert data["records"][0]["contributor_type"] == "ai_agent"
