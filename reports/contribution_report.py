"""
reports/contribution_report.py

The review/narrative agent's entire job: turn a ProvenanceStore summary
into a downloadable PDF. It does not classify, judge, or verify anything —
it only renders what was tagged at generation/review time. Fetched
on-demand by the user (e.g. GET /repos/{repo}/contribution-report.pdf),
matching the pattern of your existing reports/ PDF engineering reports.
"""

from __future__ import annotations

from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Disclaimer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.grey,
        )
    )
    return styles


def generate_contribution_report(summary: dict, output_path: str) -> str:
    """
    summary: the dict returned by ProvenanceStore.summary(repo)
    output_path: where to write the PDF
    """
    styles = _styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story = []

    # --- Header ---
    story.append(Paragraph("Contribution Report", styles["Title"]))
    story.append(Paragraph(summary["repo"], styles["Heading2"]))
    generated = datetime.fromisoformat(summary["generated_at"]).strftime(
        "%B %d, %Y at %H:%M UTC"
    )
    story.append(Paragraph(f"Generated {generated}", styles["Normal"]))
    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            "This report reflects provenance metadata captured at the time "
            "each contribution was made (agent, model, human reviewer, "
            "and whether AI output was accepted verbatim or edited). It is "
            "a record of what Nakima logged, not an independent forensic "
            "determination of authorship.",
            styles["Disclaimer"],
        )
    )
    story.append(Spacer(1, 20))

    # --- Top-line summary ---
    story.append(Paragraph("Summary", styles["Heading2"]))
    top_data = [
        ["Total tracked changes", str(summary["total_records"])],
        ["Lines added", str(summary["total_lines_added"])],
        ["Lines removed", str(summary["total_lines_removed"])],
    ]
    top_table = Table(top_data, colWidths=[3 * inch, 2 * inch])
    top_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f2")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(top_table)
    story.append(Spacer(1, 20))

    # --- By contributor type ---
    story.append(Paragraph("By Contributor Type", styles["Heading2"]))
    type_rows = [["Type", "Changes", "Lines +", "Lines -"]]
    label_map = {
        "ai_agent": "AI Agent (accepted as generated)",
        "human": "Human",
        "human_edited_ai": "Human-edited AI output",
    }
    for key, stats in summary["by_contributor_type"].items():
        type_rows.append(
            [
                label_map.get(key, key),
                str(stats["count"]),
                str(stats["lines_added"]),
                str(stats["lines_removed"]),
            ]
        )
    type_table = Table(type_rows, colWidths=[2.6 * inch, 1.1 * inch, 1 * inch, 1 * inch])
    type_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2327")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
            ]
        )
    )
    story.append(type_table)
    story.append(Spacer(1, 20))

    # --- By agent ---
    if summary["by_agent"]:
        story.append(Paragraph("By Agent / Model", styles["Heading2"]))
        agent_rows = [["Agent", "Changes"]] + [
            [name, str(count)] for name, count in summary["by_agent"].items()
        ]
        agent_table = Table(agent_rows, colWidths=[3 * inch, 1.5 * inch])
        agent_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2327")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(agent_table)
        story.append(Spacer(1, 20))

    # --- By human ---
    if summary["by_human"]:
        story.append(Paragraph("By Human Reviewer/Author", styles["Heading2"]))
        human_rows = [["Contributor", "Changes"]] + [
            [name, str(count)] for name, count in summary["by_human"].items()
        ]
        human_table = Table(human_rows, colWidths=[3 * inch, 1.5 * inch])
        human_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2327")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(human_table)
        story.append(Spacer(1, 20))

    # --- Detail log ---
    story.append(PageBreak())
    story.append(Paragraph("Detail Log", styles["Heading2"]))
    detail_rows = [["File", "Type", "Agent/Human", "Issue", "Verbatim"]]
    for r in summary["records"]:
        who = r.get("agent_name") or r.get("human_actor") or "-"
        detail_rows.append(
            [
                r["file_path"],
                r["contributor_type"],
                who,
                r.get("issue_ref") or "-",
                str(r.get("accepted_verbatim")) if r.get("accepted_verbatim") is not None else "-",
            ]
        )
    detail_table = Table(
        detail_rows, colWidths=[1.8 * inch, 1.1 * inch, 1.3 * inch, 0.7 * inch, 0.9 * inch]
    )
    detail_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2327")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
            ]
        )
    )
    story.append(detail_table)

    doc.build(story)
    return output_path
