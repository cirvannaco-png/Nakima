"""Configuration Security module of the NSIL — reviews Dockerfiles and
GitHub Actions workflows for insecure defaults. Deterministic, rule-based;
same philosophy as security/secret_scanner.py. Kubernetes manifests, reverse
proxy configs, and cloud IAM policies from the EIP spec's list are not
covered — Nakima has no deployment target that produces any of those yet
(see core/config.py's REPORTS_DIR comment on the same theme), so adding
rules for formats nothing in this repo generates would be untested,
unmaintainable surface area rather than real coverage.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from security.secret_scanner import SECRET_PATTERNS


@dataclass
class ConfigFinding:
    rule: str
    severity: str
    file_path: str
    detail: str


class ConfigSecurityScanner:
    def scan(self, repo_dir: Path) -> list[ConfigFinding]:
        repo_dir = Path(repo_dir)
        findings: list[ConfigFinding] = []
        findings.extend(self._scan_dockerfiles(repo_dir))
        findings.extend(self._scan_workflows(repo_dir))
        return findings

    # -- Dockerfiles --------------------------------------------------

    def _scan_dockerfiles(self, repo_dir: Path) -> list[ConfigFinding]:
        findings = []
        candidates = list(repo_dir.rglob("Dockerfile*"))
        for path in candidates:
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            rel_path = str(path.relative_to(repo_dir))
            findings.extend(self._check_dockerfile_text(rel_path, text))
        return findings

    def _check_dockerfile_text(self, rel_path: str, text: str) -> list[ConfigFinding]:
        findings = []
        lines = text.splitlines()

        if not re.search(r"(?im)^\s*USER\s+\S+", text):
            findings.append(
                ConfigFinding(
                    rule="dockerfile_no_user",
                    severity="medium",
                    file_path=rel_path,
                    detail="No USER instruction — the container runs as root by default.",
                )
            )

        for line in lines:
            if re.match(r"(?i)^\s*FROM\s+\S+:latest\b", line) or re.match(r"(?i)^\s*FROM\s+[^:@\s]+\s*$", line):
                findings.append(
                    ConfigFinding(
                        rule="dockerfile_unpinned_base_image",
                        severity="low",
                        file_path=rel_path,
                        detail=f"Base image is unpinned (':latest' or no tag): {line.strip()}",
                    )
                )
            if re.match(r"(?i)^\s*ADD\s+\S", line) and "://" not in line:
                findings.append(
                    ConfigFinding(
                        rule="dockerfile_add_instead_of_copy",
                        severity="low",
                        file_path=rel_path,
                        detail=f"ADD used for a local path — COPY is preferred unless remote-URL/archive "
                        f"extraction is actually needed: {line.strip()}",
                    )
                )
            if re.match(r"(?i)^\s*ENV\s", line):
                for _name, pattern, _severity in SECRET_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            ConfigFinding(
                                rule="dockerfile_secret_in_env",
                                severity="critical",
                                file_path=rel_path,
                                detail="ENV instruction appears to bake a secret into the image layer history.",
                            )
                        )
                        break

        return findings

    # -- GitHub Actions workflows --------------------------------------

    def _scan_workflows(self, repo_dir: Path) -> list[ConfigFinding]:
        findings = []
        workflow_dir = repo_dir / ".github" / "workflows"
        if not workflow_dir.is_dir():
            return findings

        for path in sorted(workflow_dir.glob("*.y*ml")):
            try:
                doc = yaml.safe_load(path.read_text(errors="ignore"))
            except yaml.YAMLError:
                continue  # malformed YAML isn't this scanner's job to flag
            if not isinstance(doc, dict):
                continue
            rel_path = str(path.relative_to(repo_dir))
            findings.extend(self._check_workflow_doc(rel_path, doc, path.read_text(errors="ignore")))
        return findings

    def _check_workflow_doc(self, rel_path: str, doc: dict, raw_text: str) -> list[ConfigFinding]:
        findings = []

        triggers = doc.get(True) or doc.get("on") or {}  # PyYAML parses bare `on:` key as boolean True in YAML 1.1
        trigger_names = set(triggers) if isinstance(triggers, dict) else (
            {triggers} if isinstance(triggers, str) else set(triggers or [])
        )
        has_pull_request_target = "pull_request_target" in trigger_names
        has_checkout_of_pr_head = bool(re.search(r"(?i)ref:\s*\$\{\{\s*github\.event\.pull_request\.head", raw_text))
        if has_pull_request_target and has_checkout_of_pr_head:
            findings.append(
                ConfigFinding(
                    rule="workflow_pwn_request",
                    severity="high",
                    file_path=rel_path,
                    detail="pull_request_target combined with checking out the PR head ref runs untrusted "
                    "fork code with access to repo secrets (classic 'pwn request' pattern).",
                )
            )

        permissions = doc.get("permissions")
        if permissions == "write-all" or (isinstance(permissions, dict) and permissions.get("contents") == "write-all"):
            findings.append(
                ConfigFinding(
                    rule="workflow_overbroad_permissions",
                    severity="medium",
                    file_path=rel_path,
                    detail="permissions: write-all grants the GITHUB_TOKEN far more access than most jobs need.",
                )
            )

        if re.search(r"(?i)echo\s+.*\$\{\{\s*secrets\.", raw_text):
            findings.append(
                ConfigFinding(
                    rule="workflow_secret_echoed",
                    severity="high",
                    file_path=rel_path,
                    detail="A step appears to echo a secrets.* value directly, which prints it to the "
                    "(often not fully redacted) build log.",
                )
            )

        return findings
