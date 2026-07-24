"""Nakima Security Intelligence Layer — the orchestrator from the EIP
spec's NSIL proposal. Runs Secret Detection and Configuration Security
locally (pure Python, no sandbox needed — see security/secret_scanner.py
and security/config_scanner.py), SAST + Dependency Audit via
SecurityAgent (which needs Docker; see agents/security_agent.py), and
optionally DAST (security/dast.py) and the Pentest Simulator
(security/pentest_simulator.py) against a live target URL. Persists
every finding with a stable fingerprint so re-scans can tell "still open"
apart from "newly resolved" instead of treating each scan as an unrelated
snapshot — this is the Security Regression Testing concept from the spec.

The Pentest Simulator is gated more conservatively than DAST: it requires
both target_url AND run_pentest_simulator=True (DAST alone only needs
target_url) — active exploitation checks shouldn't run just because a URL
was supplied for a read-only scan. The API layer additionally requires
GitHub ownership verification (security/target_binding.py) whenever
target_url is set at all, covering both.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentRequest
from agents.security_agent import SecurityAgent
from models.security import SecurityFinding, fingerprint
from security.config_scanner import ConfigSecurityScanner
from security.dast import DASTScanner
from security.pentest_simulator import PentestSimulator
from security.risk_scoring import RiskScorer
from security.secret_scanner import SecretScanner
from security.virus_scanner import VirusScanner, VirusScannerUnavailable

logger = logging.getLogger(__name__)


@dataclass
class NSILResult:
    score: float
    counts_by_severity: dict[str, int]
    total_open: int
    new_finding_count: int
    resolved_finding_count: int
    scanners_run: list[str] = field(default_factory=list)
    scanners_skipped: list[str] = field(default_factory=list)


class SecurityIntelligenceLayer:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id
        self.risk_scorer = RiskScorer()

    async def scan(
        self,
        repo_dir: Path,
        include_agent_scanners: bool = True,
        target_url: str | None = None,
        run_pentest_simulator: bool = False,
    ) -> NSILResult:
        """`include_agent_scanners=False` skips SAST (bandit) and
        Dependency Audit (safety) — used by orchestrator/workflow.py's
        per-task Security Gate, where ValidationPipeline's 'security'
        stage (execution/tool_registry.py) already runs both of those
        tools as a blocking check on every task. Running them a second
        time here would just re-invoke bandit/safety redundantly. The
        on-demand `POST /security/{repo}/scan` endpoint calls with the
        default `True` to get full NSIL coverage including SAST and
        dependency findings tracked with regression history, which the
        validation pipeline's pass/fail result doesn't provide.

        `target_url`, if given, runs DAST against it — observational
        checks only (security/dast.py), never requested unless the
        caller explicitly provides a URL. There's no default target and
        no crawling to discover one; a URL only gets hit if a caller
        passed it in, same explicit-opt-in posture as
        include_agent_scanners.

        `run_pentest_simulator=True` additionally runs the Pentest
        Simulator (security/pentest_simulator.py) against target_url —
        active, if non-destructive, checks. Requires target_url to also
        be set; a pentest flag with no target does nothing.
        """
        repo_dir = Path(repo_dir)
        scanners_run: list[str] = []
        scanners_skipped: list[str] = []

        current: dict[str, dict] = {}  # fingerprint -> finding dict

        try:
            for secret_finding in SecretScanner().scan(repo_dir):
                fp = fingerprint(
                    "secret", secret_finding.pattern_name, secret_finding.file_path, secret_finding.line_number
                )
                current[fp] = {
                    "source": "secret",
                    "rule": secret_finding.pattern_name,
                    "severity": secret_finding.severity,
                    "file_path": secret_finding.file_path,
                    "line_number": secret_finding.line_number,
                    "detail": f"Possible secret ({secret_finding.pattern_name}): {secret_finding.redacted_preview}",
                }
            scanners_run.append("secret_detection")
        except Exception as e:
            logger.warning(f"NSIL: secret scan failed, skipping: {e}")
            scanners_skipped.append("secret_detection")

        try:
            for config_finding in ConfigSecurityScanner().scan(repo_dir):
                fp = fingerprint("config", config_finding.rule, config_finding.file_path, None)
                current[fp] = {
                    "source": "config",
                    "rule": config_finding.rule,
                    "severity": config_finding.severity,
                    "file_path": config_finding.file_path,
                    "line_number": None,
                    "detail": config_finding.detail,
                }
            scanners_run.append("config_security")
        except Exception as e:
            logger.warning(f"NSIL: config security scan failed, skipping: {e}")
            scanners_skipped.append("config_security")

        try:
            for virus_finding in VirusScanner().scan_directory(repo_dir):
                fp = fingerprint("virus", virus_finding.threat_name, virus_finding.file_path, None)
                current[fp] = {
                    "source": "virus",
                    "rule": virus_finding.threat_name,
                    "severity": "critical",  # a real malware match is always critical, not a judgment call
                    "file_path": virus_finding.file_path,
                    "line_number": None,
                    "detail": virus_finding.detail,
                }
            scanners_run.append("virus")
        except VirusScannerUnavailable as e:
            logger.warning(f"NSIL: virus scan skipped, clamd unavailable: {e}")
            scanners_skipped.append("virus")

        if target_url:
            try:
                for dast_finding in await DASTScanner().scan(target_url):
                    fp = fingerprint("dast", dast_finding.rule, target_url, None)
                    current[fp] = {
                        "source": "dast",
                        "rule": dast_finding.rule,
                        "severity": dast_finding.severity,
                        "file_path": target_url,
                        "line_number": None,
                        "detail": dast_finding.detail,
                    }
                scanners_run.append("dast")
            except Exception as e:
                logger.warning(f"NSIL: DAST scan against {target_url} failed unexpectedly, skipping: {e}")
                scanners_skipped.append("dast")

            if run_pentest_simulator:
                try:
                    for pentest_finding in await PentestSimulator().scan(target_url):
                        fp = fingerprint("pentest", pentest_finding.rule, target_url, None)
                        current[fp] = {
                            "source": "pentest",
                            "rule": pentest_finding.rule,
                            "severity": pentest_finding.severity,
                            "file_path": target_url,
                            "line_number": None,
                            "detail": pentest_finding.detail,
                        }
                    scanners_run.append("pentest")
                except Exception as e:
                    logger.warning(f"NSIL: Pentest scan against {target_url} failed unexpectedly, skipping: {e}")
                    scanners_skipped.append("pentest")

        agent = None
        if include_agent_scanners:
            try:
                agent = SecurityAgent()
            except Exception as e:
                logger.warning(f"NSIL: no AI provider configured, skipping agent-backed scanners: {e}")
                scanners_skipped.extend(["sast", "dependency_audit"])

        if agent is not None:
            for source, action, mapper in (
                ("sast", "sast_scan", self._map_sast_finding),
                ("dependency_audit", "audit_dependencies", self._map_dependency_finding),
            ):
                try:
                    resp = await agent.execute(AgentRequest(action=action, context={"repo_dir": str(repo_dir)}))
                    if resp.success:
                        for item in mapper(resp.result):
                            fp = fingerprint(source, item["rule"], item["file_path"], item.get("line_number"))
                            current[fp] = {"source": source, **item}
                        scanners_run.append(source)
                    else:
                        scanners_skipped.append(source)
                except Exception as e:
                    # Most commonly: no Docker daemon available in this
                    # environment. A missing scanner degrades the result
                    # rather than failing the whole NSIL run — same
                    # philosophy as CognitiveEngine's provider fallback.
                    logger.warning(f"NSIL: {source} scan failed, skipping: {e}")
                    scanners_skipped.append(source)

        new_count, resolved_count = await self._reconcile(current)

        open_severities = [f.severity for f in await self._open_findings()]
        risk = self.risk_scorer.score(open_severities)

        return NSILResult(
            score=risk.score,
            counts_by_severity=risk.counts_by_severity,
            total_open=risk.total_findings,
            new_finding_count=new_count,
            resolved_finding_count=resolved_count,
            scanners_run=scanners_run,
            scanners_skipped=scanners_skipped,
        )

    def _map_sast_finding(self, result: dict) -> list[dict]:
        return [
            {
                "rule": f["rule"] or "unknown",
                "severity": f["severity"] if f["severity"] in ("critical", "high", "medium", "low") else "medium",
                "file_path": f["file"],
                "line_number": f.get("line"),
                "detail": f"{f.get('title', '')}: {f.get('detail', '')}".strip(": "),
            }
            for f in result.get("findings", [])
        ]

    def _map_dependency_finding(self, result: dict) -> list[dict]:
        return [
            {
                "rule": v.get("vulnerability", "unknown"),
                "severity": "high",  # `safety`'s free-tier output doesn't carry a severity field
                "file_path": "requirements.txt",
                "line_number": None,
                "detail": f"{v.get('package')} {v.get('installed')}: {v.get('vulnerability')}",
            }
            for v in result.get("vulnerabilities", [])
        ]

    async def _open_findings(self) -> list[SecurityFinding]:
        stmt = select(SecurityFinding).where(
            SecurityFinding.repository_id == self.repository_id, SecurityFinding.status == "open"
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _reconcile(self, current: dict[str, dict]) -> tuple[int, int]:
        """Diffs `current` (this scan's fingerprints) against what's
        already stored as open in the DB. New fingerprints are inserted;
        fingerprints seen before get last_seen_at bumped (and are reopened
        if they'd been marked resolved); previously-open fingerprints not
        seen this time are marked resolved. Returns (new_count,
        resolved_count).
        """
        stmt = select(SecurityFinding).where(SecurityFinding.repository_id == self.repository_id)
        existing = {f.fingerprint: f for f in (await self.session.execute(stmt)).scalars().all()}

        now = datetime.now(UTC).replace(tzinfo=None)
        new_count = 0

        for fp, data in current.items():
            row = existing.get(fp)
            if row is None:
                self.session.add(
                    SecurityFinding(
                        repository_id=self.repository_id,
                        fingerprint=fp,
                        first_seen_at=now,
                        last_seen_at=now,
                        status="open",
                        **data,
                    )
                )
                new_count += 1
            else:
                row.last_seen_at = now
                if row.status == "resolved":
                    row.status = "open"
                    row.resolved_at = None

        resolved_count = 0
        for fp, row in existing.items():
            if fp not in current and row.status == "open":
                row.status = "resolved"
                row.resolved_at = now
                resolved_count += 1

        await self.session.commit()
        return new_count, resolved_count
