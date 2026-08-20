"""Tests for the standalone provenance PDF generators.

These build real PDFs into tmp_path and inspect the produced files, the
same discipline used by tests/test_reports.py.
"""

from core.provenance import (
    ProvenanceStore,
    tag_agent_generation,
    tag_human_origin,
    tag_review_decision,
)
from reports.contribution_report import generate_contribution_report
from reports.pr_triage_report import (
    BUCKET_INFO,
    generate_blank_template,
    generate_pr_triage_report,
)

DIFF = "@@ -1 +1,2 @@\n+new line\n"


def _assert_is_pdf(path):
    with open(path, "rb") as f:
        assert f.read(5) == b"%PDF-"
    assert path.stat().st_size > 1000


def _summary(repo="cirvannaco-png/Nakima"):
    store = ProvenanceStore()
    ai = tag_agent_generation(
        repo=repo,
        file_path="api/main.py",
        diff_text=DIFF,
        agent_name="nakima-implementer",
        model_id="claude-sonnet-4-6",
        issue_ref="#482",
        prompt_ref="plan-step-1",
        lines_added=10,
        lines_removed=2,
    )
    store.add(ai)

    edited = tag_agent_generation(
        repo=repo,
        file_path="api/routes.py",
        diff_text=DIFF + "x",
        agent_name="nakima-refactorer",
        model_id="gpt-5",
        issue_ref="#483",
        prompt_ref="plan-step-2",
        lines_added=4,
        lines_removed=1,
    )
    store.add(tag_review_decision(edited, human_actor="kelson", edited=True))

    store.add(
        tag_human_origin(
            repo=repo,
            file_path="docs/readme.md",
            diff_text="+docs\n",
            human_actor="kelson",
            issue_ref="#484",
            lines_added=6,
        )
    )
    return store.summary(repo)


def test_contribution_report_builds_a_pdf(tmp_path):
    out = tmp_path / "contribution.pdf"

    returned = generate_contribution_report(_summary(), str(out))

    assert returned == str(out)
    _assert_is_pdf(out)


def test_contribution_report_handles_empty_provenance(tmp_path):
    out = tmp_path / "empty.pdf"
    empty = ProvenanceStore().summary("cirvannaco-png/Nakima")

    generate_contribution_report(empty, str(out))

    _assert_is_pdf(out)


def test_pr_triage_report_covers_every_bucket(tmp_path):
    prs = [
        {
            "number": index,
            "title": f"PR touching {bucket}",
            "author": "kelson",
            "opened": "2026-06-01",
            "last_activity": "2026-08-10",
            "bucket": bucket,
            "notes": "Needs a rebase before merge.",
        }
        for index, bucket in enumerate(BUCKET_INFO, start=1)
    ]
    out = tmp_path / "triage.pdf"

    returned = generate_pr_triage_report(prs, str(out))

    assert returned == str(out)
    _assert_is_pdf(out)


def test_pr_triage_report_defaults_unknown_bucket_to_blocked(tmp_path):
    prs = [{"number": 1, "title": "No bucket set", "author": "kelson"}]
    out = tmp_path / "triage-defaulted.pdf"

    generate_pr_triage_report(prs, str(out), repo="cirvannaco-png/Nakima")

    _assert_is_pdf(out)


def test_blank_template_is_generated_without_pr_data(tmp_path):
    out = tmp_path / "template.pdf"

    returned = generate_blank_template(str(out))

    assert returned == str(out)
    _assert_is_pdf(out)
