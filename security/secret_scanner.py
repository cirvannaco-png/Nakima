"""Secret Detection module of the NSIL. Deterministic regex matching, same
"heuristic, not NLP/ML" philosophy as PolicyChecker and
neis/reasoning/evidence_engine.py's constraint matching — false negatives
(a real secret in a shape this doesn't recognize) are expected; false
positives are handled by keeping patterns specific rather than generic.

Findings never include the actual secret value — only a redacted preview
(first 4 / last 4 characters). Reporting a scan result should never itself
become a secret-exposure incident.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from neis.analyzers.project_modeler import IGNORED_DIRS

# (pattern_name, compiled_regex, severity). Order matters only for
# readability — every file is checked against every pattern regardless.
# Public (no leading underscore) because security/config_scanner.py reuses
# it to flag secrets baked into Dockerfile ENV instructions, rather than
# maintaining a second copy of the same patterns.
SECRET_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "critical"),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"),
        "critical",
    ),
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "critical"),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "critical"),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "high"),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"), "critical"),
    (
        "generic_api_key_assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token)\b\s*[:=]\s*['\"]([A-Za-z0-9_\-]{20,})['\"]"),
        "medium",
    ),
    ("jwt_looking_secret", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "medium"),
]

# Files that legitimately contain secret-shaped strings without being a
# leak — the pattern's own docs/tests, or a documented placeholder.
_SKIP_SUFFIXES = {".md", ".rst"}
_SKIP_NAMES = {".env.example"}

_MAX_FILE_BYTES = 2_000_000  # skip anything that isn't plausibly source/config text


@dataclass
class SecretFinding:
    pattern_name: str
    severity: str
    file_path: str
    line_number: int
    redacted_preview: str


def _redact(match_text: str) -> str:
    if len(match_text) <= 8:
        return "*" * len(match_text)
    return f"{match_text[:4]}{'*' * (len(match_text) - 8)}{match_text[-4:]}"


class SecretScanner:
    def scan(self, repo_dir: Path) -> list[SecretFinding]:
        repo_dir = Path(repo_dir)
        findings: list[SecretFinding] = []
        for file_path in repo_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in file_path.parts):
                continue
            if file_path.suffix in _SKIP_SUFFIXES or file_path.name in _SKIP_NAMES:
                continue
            try:
                if file_path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = file_path.read_text(errors="ignore")
            except OSError:
                continue

            rel_path = str(file_path.relative_to(repo_dir))
            for line_number, line in enumerate(text.splitlines(), start=1):
                for pattern_name, pattern, severity in SECRET_PATTERNS:
                    m = pattern.search(line)
                    if m:
                        findings.append(
                            SecretFinding(
                                pattern_name=pattern_name,
                                severity=severity,
                                file_path=rel_path,
                                line_number=line_number,
                                redacted_preview=_redact(m.group(0)),
                            )
                        )
        return findings
