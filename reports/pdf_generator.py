"""Assembles an Engineering Intelligence Report PDF for one repository.
Every section is optional and rendered only if there's real data behind
it — no section is ever padded with placeholder text to look complete.
See reports/__init__.py.
"""

import logging
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from intelligence.decision_registry import DecisionRegistry
from intelligence.event_log import EventLog
from models.neis.evolution_roadmap import EvolutionRoadmap, RoadmapStatus
from models.neis.project_reality import ProjectRealityModel
from models.neis.user_intent import UserIntent
from models.report import EngineeringReport
from models.repository import Repository
from models.security import SecurityFinding
from neis.reasoning.evidence_engine import EvidenceEngine
from security.risk_scoring import RiskScorer

logger = logging.getLogger(__name__)

_MAX_DECISIONS = 20
_MAX_EVENTS = 20
_MAX_ROADMAP_ITEMS = 15


class ReportGenerator:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id
        self.styles = getSampleStyleSheet()
        self.styles.add(
            ParagraphStyle(name="SectionHeading", parent=self.styles["Heading2"], spaceBefore=18, spaceAfter=6)
        )

    async def generate(self) -> EngineeringReport:
        repo = await self.session.get(Repository, self.repository_id)
        if not repo:
            raise ValueError(f"No repository with id={self.repository_id}")

        reality = await self._latest_reality()
        intent = await self._active_intent()
        roadmap = await self._active_roadmap()
        decisions = await DecisionRegistry(self.session, self.repository_id).list_for_repository(limit=_MAX_DECISIONS)
        events = await EventLog(self.session, self.repository_id).list_for_repository(limit=_MAX_EVENTS)
        open_findings = await self._open_security_findings()
        intent_confidence = EvidenceEngine().score_intent_confidence(intent)

        version = await self._next_version()
        file_path = self._file_path(repo.full_name, version)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        sections_included: list[str] = []
        story: list = []

        story.extend(self._render_title(repo, version))

        exec_summary = self._executive_summary(
            reality, intent, roadmap, decisions, events, intent_confidence, open_findings
        )
        story.extend(self._render_section("Executive Summary", [Paragraph(exec_summary, self.styles["BodyText"])]))
        sections_included.append("executive_summary")

        if reality:
            story.extend(self._render_section("Project DNA", self._render_project_dna(reality)))
            sections_included.append("project_dna")

        story.extend(self._render_section("Intent Alignment", self._render_intent_alignment(intent, intent_confidence)))
        sections_included.append("intent_alignment")

        if decisions:
            story.extend(self._render_section("Engineering Decisions", self._render_decisions(decisions)))
            sections_included.append("engineering_decisions")

        if events:
            story.extend(self._render_section("Engineering Timeline", self._render_events(events)))
            sections_included.append("engineering_timeline")

        if open_findings:
            story.extend(self._render_section("Security", self._render_security(open_findings)))
            sections_included.append("security")

        if roadmap and roadmap.items:
            story.extend(self._render_section("Recommendations", self._render_roadmap(roadmap)))
            sections_included.append("recommendations")

        if reality and reality.health_components:
            story.extend(self._render_section("Technical Debt", self._render_technical_debt(reality)))
            sections_included.append("technical_debt")

        doc = SimpleDocTemplate(str(file_path), pagesize=LETTER, title=f"Nakima Engineering Intelligence Report — {repo.full_name}")
        doc.build(story)

        report = EngineeringReport(
            repository_id=self.repository_id,
            version=version,
            file_path=str(file_path),
            executive_summary=exec_summary,
            sections_included=sections_included,
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        return report

    # -- data gathering ----------------------------------------------------

    async def _latest_reality(self) -> ProjectRealityModel | None:
        stmt = (
            select(ProjectRealityModel)
            .where(ProjectRealityModel.repository_id == self.repository_id)
            .order_by(ProjectRealityModel.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _active_intent(self) -> UserIntent | None:
        stmt = select(UserIntent).where(
            UserIntent.repository_id == self.repository_id, UserIntent.is_active.is_(True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _active_roadmap(self) -> EvolutionRoadmap | None:
        stmt = select(EvolutionRoadmap).where(
            EvolutionRoadmap.repository_id == self.repository_id,
            EvolutionRoadmap.status == RoadmapStatus.ACTIVE,
        )
        roadmap = (await self.session.execute(stmt)).scalar_one_or_none()
        if roadmap:
            await self.session.refresh(roadmap, attribute_names=["items"])
        return roadmap

    async def _open_security_findings(self) -> list[SecurityFinding]:
        stmt = select(SecurityFinding).where(
            SecurityFinding.repository_id == self.repository_id, SecurityFinding.status == "open"
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _next_version(self) -> int:
        stmt = select(func.max(EngineeringReport.version)).where(
            EngineeringReport.repository_id == self.repository_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one_or_none()
        return (current_max or 0) + 1

    def _file_path(self, repo_full_name: str, version: int) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", repo_full_name)
        return Path(settings.REPORTS_DIR) / safe_name / f"v{version}.pdf"

    # -- rendering -----------------------------------------------------

    def _render_title(self, repo: Repository, version: int) -> list:
        return [
            Paragraph("Nakima Engineering Intelligence Report", self.styles["Title"]),
            Paragraph(f"{repo.full_name} — Report v{version}", self.styles["Heading3"]),
            Spacer(1, 0.3 * inch),
        ]

    def _render_section(self, heading: str, flowables: list) -> list:
        return [Paragraph(heading, self.styles["SectionHeading"]), *flowables]

    def _executive_summary(self, reality, intent, roadmap, decisions, events, intent_confidence, open_findings) -> str:
        parts = []
        if reality and reality.health_score is not None:
            parts.append(f"Repository health score is {reality.health_score:.1f}/100.")
        else:
            parts.append("No NEIS analysis has been run yet — health score unavailable.")

        if open_findings:
            risk = RiskScorer().score([f.severity for f in open_findings])
            parts.append(
                f"Security score is {risk.score:.0f}/100 with {risk.total_findings} open finding(s) "
                f"({risk.counts_by_severity.get('critical', 0)} critical, {risk.counts_by_severity.get('high', 0)} high)."
            )
        else:
            parts.append("No open security findings on record — run POST /security/{repo}/scan if one hasn't run yet.")

        parts.append(
            f"Intent confidence is {intent_confidence.score:.2f} "
            f"({'well-specified' if not intent_confidence.is_low_confidence else 'underspecified'})."
        )

        passed = sum(1 for e in events if e.verification_status == "passed")
        failed = sum(1 for e in events if e.verification_status == "failed")
        if events:
            parts.append(f"{len(events)} recent engineering event(s) recorded: {passed} passed, {failed} failed.")

        if decisions:
            parts.append(f"{len(decisions)} engineering decision(s) on record.")

        if roadmap and roadmap.items:
            open_items = [i for i in roadmap.items if i.status.value == "proposed"]
            parts.append(f"{len(open_items)} open recommendation(s) from the active NEIS roadmap.")

        return " ".join(parts)

    def _render_project_dna(self, reality: ProjectRealityModel) -> list:
        rows = [["Field", "Value"]]
        rows.append(["Languages", ", ".join(f"{k}: {v} files" for k, v in (reality.languages or {}).items())])
        rows.append(["Files", str(reality.file_count)])
        rows.append(["Test files", str(reality.test_file_count)])
        rows.append(["Dependencies", str(len(reality.dependencies or []))])
        rows.append(["Health score", f"{reality.health_score:.1f}/100" if reality.health_score is not None else "n/a"])
        rows.append(["Snapshot taken", reality.created_at.strftime("%Y-%m-%d %H:%M UTC")])
        return [self._table(rows)]

    def _render_intent_alignment(self, intent: UserIntent | None, intent_confidence) -> list:
        flowables = []
        if not intent:
            flowables.append(Paragraph("No UserIntent has been recorded for this repository.", self.styles["BodyText"]))
            return flowables
        flowables.append(Paragraph(f"Intent confidence score: {intent_confidence.score:.2f}", self.styles["BodyText"]))
        if intent.goals:
            flowables.append(Paragraph("Goals: " + "; ".join(intent.goals), self.styles["BodyText"]))
        if intent.constraints:
            flowables.append(Paragraph("Constraints: " + "; ".join(intent.constraints), self.styles["BodyText"]))
        if intent_confidence.missing:
            flowables.append(
                Paragraph("Gaps: " + "; ".join(intent_confidence.missing), self.styles["BodyText"])
            )
        return flowables

    def _render_decisions(self, decisions) -> list:
        rows = [["Date", "Decision", "Author"]]
        for d in decisions:
            rows.append([d.created_at.strftime("%Y-%m-%d"), d.decision[:80], d.author])
        return [self._table(rows)]

    def _render_events(self, events) -> list:
        rows = [["Date", "Task", "Verification", "Risk"]]
        for e in events:
            rows.append([e.timestamp.strftime("%Y-%m-%d"), e.task_description[:60], e.verification_status, e.risk_level])
        return [self._table(rows)]

    def _render_roadmap(self, roadmap: EvolutionRoadmap) -> list:
        flowables = [Paragraph(roadmap.summary, self.styles["BodyText"]), Spacer(1, 0.1 * inch)]
        rows = [["Priority", "Category", "Title", "Effort"]]
        for item in sorted(roadmap.items, key=lambda i: i.priority_score, reverse=True)[:_MAX_ROADMAP_ITEMS]:
            rows.append([f"{item.priority_score:.1f}", item.category.value, item.title[:60], item.effort_estimate.value])
        flowables.append(self._table(rows))
        return flowables

    def _render_security(self, findings: list[SecurityFinding]) -> list:
        risk = RiskScorer().score([f.severity for f in findings])
        flowables = [
            Paragraph(
                f"Security score: {risk.score:.0f}/100 — "
                f"{risk.counts_by_severity.get('critical', 0)} critical, "
                f"{risk.counts_by_severity.get('high', 0)} high, "
                f"{risk.counts_by_severity.get('medium', 0)} medium, "
                f"{risk.counts_by_severity.get('low', 0)} low.",
                self.styles["BodyText"],
            ),
            Spacer(1, 0.1 * inch),
        ]
        rows = [["Severity", "Source", "Rule", "File"]]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for f in sorted(findings, key=lambda f: severity_order.get(f.severity, 4))[:30]:
            rows.append([f.severity, f.source, f.rule[:40], f.file_path[:40]])
        flowables.append(self._table(rows))
        return flowables

    def _render_technical_debt(self, reality: ProjectRealityModel) -> list:
        rows = [["Metric", "Value"]]
        for key, value in (reality.health_components or {}).items():
            rows.append([key.replace("_", " ").title(), f"{value:.3f}" if isinstance(value, float) else str(value)])
        return [self._table(rows)]

    def _table(self, rows: list[list[str]]) -> Table:
        table = Table(rows, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
                ]
            )
        )
        return table
