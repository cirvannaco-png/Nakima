"""
core/provenance.py

Captures contribution provenance AT THE POINT OF WRITING — not by
inspecting finished code afterward. Every diff/commit that flows through
Nakima's orchestrator (agent-generated) or through the review UI
(human-edited/approved) gets tagged here, before it ever hits git.

Design principle: we never guess whether code is AI-written. We know,
because we tagged it when it was created.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ContributorType(str, Enum):
    AI_AGENT = "ai_agent"
    HUMAN = "human"
    HUMAN_EDITED_AI = "human_edited_ai"  # AI proposed, human modified before accept


@dataclass
class ProvenanceRecord:
    """One record per diff hunk or commit, capturing who/what produced it."""

    record_id: str
    repo: str
    commit_sha: str | None
    file_path: str
    hunk_hash: str  # hash of the diff hunk content, for integrity
    contributor_type: ContributorType
    agent_name: str | None = None  # e.g. "nakima-implementer", "claude-sonnet-4-6"
    model_id: str | None = None  # specific model string if AI-originated
    issue_ref: str | None = None  # GitHub issue/PR number that triggered this
    prompt_ref: str | None = None  # pointer to the prompt/plan step, not raw prompt text
    human_actor: str | None = None  # GitHub username, if human wrote or edited
    accepted_verbatim: bool | None = None  # True if AI output merged with no human edits
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    lines_added: int = 0
    lines_removed: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["contributor_type"] = self.contributor_type.value
        return d

    def to_git_trailer(self) -> str:
        """
        Renders this record as git commit trailers, so provenance travels
        with the commit itself and survives outside the Nakima DB.

        Example:
            Nakima-Contributor: ai_agent
            Nakima-Agent: nakima-implementer
            Nakima-Model: claude-sonnet-4-6
            Nakima-Issue: #482
            Nakima-Accepted-Verbatim: true
        """
        lines = [f"Nakima-Contributor: {self.contributor_type.value}"]
        if self.agent_name:
            lines.append(f"Nakima-Agent: {self.agent_name}")
        if self.model_id:
            lines.append(f"Nakima-Model: {self.model_id}")
        if self.issue_ref:
            lines.append(f"Nakima-Issue: {self.issue_ref}")
        if self.human_actor:
            lines.append(f"Nakima-Human: {self.human_actor}")
        if self.accepted_verbatim is not None:
            lines.append(f"Nakima-Accepted-Verbatim: {str(self.accepted_verbatim).lower()}")
        return "\n".join(lines)


def hunk_hash(diff_text: str) -> str:
    return hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:16]


def tag_agent_generation(
    *,
    repo: str,
    file_path: str,
    diff_text: str,
    agent_name: str,
    model_id: str,
    issue_ref: str,
    prompt_ref: str,
    lines_added: int,
    lines_removed: int,
) -> ProvenanceRecord:
    """Call this the moment the orchestrator's Implementer step produces a diff,
    before it's shown to the user for review."""
    return ProvenanceRecord(
        record_id=hunk_hash(diff_text + agent_name + str(datetime.now())),
        repo=repo,
        commit_sha=None,
        file_path=file_path,
        hunk_hash=hunk_hash(diff_text),
        contributor_type=ContributorType.AI_AGENT,
        agent_name=agent_name,
        model_id=model_id,
        issue_ref=issue_ref,
        prompt_ref=prompt_ref,
        accepted_verbatim=None,  # unknown until reviewed
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def tag_review_decision(
    record: ProvenanceRecord,
    *,
    human_actor: str,
    edited: bool,
    final_diff_text: str | None = None,
) -> ProvenanceRecord:
    """Call this when a human approves/edits a diff in the review UI.
    Mutates the record's classification based on what actually happened,
    rather than inferring it later."""
    record.human_actor = human_actor
    record.accepted_verbatim = not edited
    if edited:
        record.contributor_type = ContributorType.HUMAN_EDITED_AI
        if final_diff_text:
            record.hunk_hash = hunk_hash(final_diff_text)
    return record


def tag_human_origin(
    *,
    repo: str,
    file_path: str,
    diff_text: str,
    human_actor: str,
    issue_ref: str | None = None,
    lines_added: int = 0,
    lines_removed: int = 0,
) -> ProvenanceRecord:
    """Call this for diffs written directly by a human in the review UI,
    with no AI proposal involved at all."""
    return ProvenanceRecord(
        record_id=hunk_hash(diff_text + human_actor + str(datetime.now())),
        repo=repo,
        commit_sha=None,
        file_path=file_path,
        hunk_hash=hunk_hash(diff_text),
        contributor_type=ContributorType.HUMAN,
        human_actor=human_actor,
        issue_ref=issue_ref,
        accepted_verbatim=True,
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


class ProvenanceStore:
    """
    Minimal persistence interface. Swap this for a real SQLAlchemy model
    (matches your existing alembic/ + database/ pattern) — this in-memory
    version is here so the module is runnable/testable standalone.
    """

    def __init__(self):
        self._records: list[ProvenanceRecord] = []

    def add(self, record: ProvenanceRecord) -> None:
        self._records.append(record)

    def by_commit(self, commit_sha: str) -> list[ProvenanceRecord]:
        return [r for r in self._records if r.commit_sha == commit_sha]

    def by_repo(self, repo: str) -> list[ProvenanceRecord]:
        return [r for r in self._records if r.repo == repo]

    def set_commit_sha(self, record_id: str, commit_sha: str) -> None:
        for r in self._records:
            if r.record_id == record_id:
                r.commit_sha = commit_sha

    def summary(self, repo: str) -> dict:
        """Aggregate stats for the contribution report — this is the only
        thing the report agent is allowed to read from."""
        records = self.by_repo(repo)
        total_added = sum(r.lines_added for r in records)
        total_removed = sum(r.lines_removed for r in records)

        by_type: dict[str, dict] = {}
        for r in records:
            key = r.contributor_type.value
            by_type.setdefault(key, {"count": 0, "lines_added": 0, "lines_removed": 0})
            by_type[key]["count"] += 1
            by_type[key]["lines_added"] += r.lines_added
            by_type[key]["lines_removed"] += r.lines_removed

        by_agent: dict[str, int] = {}
        for r in records:
            if r.agent_name:
                by_agent[r.agent_name] = by_agent.get(r.agent_name, 0) + 1

        by_human: dict[str, int] = {}
        for r in records:
            if r.human_actor:
                by_human[r.human_actor] = by_human.get(r.human_actor, 0) + 1

        return {
            "repo": repo,
            "generated_at": datetime.now(UTC).isoformat(),
            "total_records": len(records),
            "total_lines_added": total_added,
            "total_lines_removed": total_removed,
            "by_contributor_type": by_type,
            "by_agent": by_agent,
            "by_human": by_human,
            "records": [r.to_dict() for r in records],
        }

    def export_json(self, repo: str, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.summary(repo), f, indent=2)
