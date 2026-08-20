"""
reports/pr_triage_report.py

Generates the PR triage PDF using the four-bucket framework:
MERGEABLE / SUPERSEDED / STALE / BLOCKED.

Usage:
    python pr_triage_report.py prs.json output.pdf

prs.json format:
[
  {
    "number": 123,
    "title": "Fix BuildJsonPayload schema mismatch",
    "author": "kelson",
    "opened": "2026-06-01",
    "last_activity": "2026-08-10",
    "bucket": "mergeable",   # mergeable | superseded | stale | blocked
    "notes": "Rebase on main, CI green, ready to merge."
  },
  ...
]

If you don't have this file yet, run with no args to generate a blank
fillable template PDF with the triage criteria instead.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BUCKET_INFO = {
    "mergeable": {
        "label": "MERGEABLE",
        "color": colors.HexColor("#1a7f37"),
        "criteria": "CI green (or fixable in <30 min), no conflicts, still solves a real problem. Action: rebase and merge this week.",
    },
    "superseded": {
        "label": "SUPERSEDED",
        "color": colors.HexColor("#8250df"),
        "criteria": "A later PR or commit already does this, or the underlying issue is closed/moot. Action: close with a comment pointing to what replaced it.",
    },
    "stale": {
        "label": "STALE",
        "color": colors.HexColor("#9a6700"),
        "criteria": "No activity in 3+ weeks, has conflicts, or was a half-finished experiment. Action: close. Reopen later if genuinely needed — an open stale PR costs more (noise, false signal on repo health) than reopening costs.",
    },
    "blocked": {
        "label": "BLOCKED",
        "color": colors.HexColor("#cf222e"),
        "criteria": "Real, wanted work that's blocked on a decision, a dependency, or your time. Action: pick at most 2-3 to actually finish this week. Defer or close the rest — an honest 'not now' beats an open PR pretending to be active.",
    },
}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, textColor=colors.grey))
    return styles


def generate_pr_triage_report(prs: list[dict], output_path: str, repo: str = "cirvannaco-png/Nakima") -> str:
    styles = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    story = []

    story.append(Paragraph("PR Triage Report", styles["Title"]))
    story.append(Paragraph(repo, styles["Heading2"]))
    story.append(Paragraph(datetime.now().strftime("Generated %B %d, %Y"), styles["Normal"]))
    story.append(Spacer(1, 16))

    # Counts by bucket
    counts = {k: 0 for k in BUCKET_INFO}
    for pr in prs:
        b = pr.get("bucket", "blocked")
        counts[b] = counts.get(b, 0) + 1

    count_rows = [["Bucket", "Count", "Meaning / Action"]]
    for key, info in BUCKET_INFO.items():
        count_rows.append([info["label"], str(counts.get(key, 0)), info["criteria"]])
    count_table = Table(count_rows, colWidths=[1.1 * inch, 0.6 * inch, 4.8 * inch])
    count_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2327")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(count_table)
    story.append(Spacer(1, 24))

    # Detail per bucket
    for key, info in BUCKET_INFO.items():
        bucket_prs = [pr for pr in prs if pr.get("bucket") == key]
        if not bucket_prs:
            continue
        story.append(Paragraph(f"{info['label']} ({len(bucket_prs)})", styles["Heading2"]))
        rows = [["#", "Title", "Author", "Last Activity", "Notes / Next Action"]]
        for pr in bucket_prs:
            rows.append(
                [
                    str(pr.get("number", "-")),
                    pr.get("title", "-"),
                    pr.get("author", "-"),
                    pr.get("last_activity", "-"),
                    pr.get("notes", "-"),
                ]
            )
        t = Table(rows, colWidths=[0.4 * inch, 1.8 * inch, 0.9 * inch, 0.9 * inch, 2.5 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), info["color"]),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 16))

    story.append(PageBreak())
    story.append(Paragraph("Triage Criteria Reference", styles["Heading2"]))
    for _key, info in BUCKET_INFO.items():
        story.append(Paragraph(f"<b>{info['label']}</b> — {info['criteria']}", styles["Normal"]))
        story.append(Spacer(1, 8))

    doc.build(story)
    return output_path


def generate_blank_template(output_path: str, repo: str = "cirvannaco-png/Nakima") -> str:
    """No PR data available — generate the fillable framework only,
    so it's ready the moment you paste in your PR list."""
    styles = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    story = [
        Paragraph("PR Triage Framework", styles["Title"]),
        Paragraph(repo, styles["Heading2"]),
        Spacer(1, 16),
        Paragraph(
            "This is the triage framework only — no live PR data was available "
            "when this was generated. Fill prs.json (see docstring in "
            "pr_triage_report.py) with your 20 PRs and re-run to get the "
            "populated version.",
            styles["Normal"],
        ),
        Spacer(1, 20),
    ]
    for _key, info in BUCKET_INFO.items():
        story.append(Paragraph(f"<b>{info['label']}</b>", styles["Heading2"]))
        story.append(Paragraph(info["criteria"], styles["Normal"]))
        story.append(Spacer(1, 12))
    doc.build(story)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        with open(sys.argv[1]) as f:
            prs = json.load(f)
        generate_pr_triage_report(prs, sys.argv[2])
        print(f"Wrote {sys.argv[2]}")
    else:
        generate_blank_template("pr_triage_template.pdf")
        print("No PR data given — wrote pr_triage_template.pdf")
