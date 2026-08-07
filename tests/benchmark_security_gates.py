"""Ground-truth benchmark for the Security Gate — not a fuzzy quality
score, a correctness check. Every case here has a known right answer
(this specific input must block / must not block), so unlike a quality
score there's no "acceptable" pass rate below 100%: any failure is a
real regression in either detection (a threat that stops blocking) or
precision (clean input that starts blocking and would jam every future
PR pipeline run). Same "deterministic, not a judgment call" posture as
security/risk_scoring.py's own docstring.

Scope: this exercises the real detection layer (SecretScanner,
ConfigSecurityScanner, VirusScanner with a mocked clamd — see
tests/test_virus_scanner.py for why clamd itself can't run here) through
the real decision layer (RiskScorer, security_gate_should_block from
orchestrator/workflow.py) end to end. It does NOT re-test NSIL's
persistence/reconciliation (tests/test_security_nsil.py already covers
that) or the CI-level bandit/safety/Trivy jobs in .github/workflows/
(those are shell commands in someone else's tool, not Python this repo
can benchmark — see BENCHMARK_SECURITY_GATES.md for how to verify those
by hand with the EICAR string).

Run standalone with a readable report:
    pytest tests/benchmark_security_gates.py -v -s
It's also collected by the normal `pytest` run (no special marker), so
CI's existing --cov-fail-under=80 test job exercises it on every PR —
consistent with the "gates that don't block CI" request this benchmark
exists to justify: CI can stay green because this proves the *product's*
gate is the one actually doing the blocking, not vibes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import security.virus_scanner as vs_mod
from orchestrator.workflow import security_gate_should_block
from security.config_scanner import ConfigSecurityScanner
from security.risk_scoring import RiskScorer
from security.secret_scanner import SecretScanner
from security.virus_scanner import VirusScanner

# Real EICAR test string — every real AV engine (including ClamAV) is
# designed to flag this specifically, per security/virus_scanner.py's own
# docstring, so using it here is the documented, intended way to verify
# a virus-scanning integration without handling real malware.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class _FakeClamdEicarAware:
    """Behaves like a real AV engine: flags content containing the EICAR
    signature as infected, everything else as clean. An "always infected"
    fake would make every case in this benchmark look like a virus hit
    (since VirusScanner.scan_directory scans every file in the repo, not
    just the one the benchmark cares about) — that's a bug in the mock,
    not something a real clamd would ever do, so mimicking the real
    signature-match behavior here is what makes this benchmark honest.
    """

    def ping(self):
        return None

    def instream(self, buf):
        content = buf.read()
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content:
            return {"stream": ("FOUND", "Eicar-Test-Signature")}
        return {"stream": ("OK", None)}


@dataclass
class GateCase:
    name: str
    expected_block: bool
    # Populates a scratch repo directory; returns nothing, just writes files.
    setup: Callable[[Path], None]
    note: str = ""


@dataclass
class GateResult:
    case: GateCase
    actual_block: bool
    severities_found: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.actual_block == self.case.expected_block


# ---------------------------------------------------------------------
# The corpus. Add a case here for every new threat class or every new
# "this must never block" regression that shows up in practice — this
# list IS the benchmark; the test functions below just execute it.
# ---------------------------------------------------------------------


def _write(repo_dir: Path, rel_path: str, content: str) -> None:
    p = repo_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


CASES: list[GateCase] = [
    GateCase(
        name="aws_access_key_committed",
        expected_block=True,
        note="AKIA-prefixed key is a critical finding in security/secret_scanner.py",
        setup=lambda d: _write(d, "config/settings.py", 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n'),
    ),
    GateCase(
        name="private_key_committed",
        expected_block=True,
        note="A raw PEM private key block is critical",
        setup=lambda d: _write(
            d, "deploy/id_rsa", "-----BEGIN RSA PRIVATE KEY-----\nMIIBOw...\n-----END RSA PRIVATE KEY-----\n"
        ),
    ),
    GateCase(
        name="malware_via_eicar",
        expected_block=True,
        note="Real virus finding — nsil.py hardcodes virus findings to severity=critical",
        setup=lambda d: _write(d, "uploads/test-file.txt", EICAR.decode("ascii")),
    ),
    GateCase(
        name="clean_repository",
        expected_block=False,
        note="No findings at all must never block",
        setup=lambda d: _write(d, "app.py", "def add(a, b):\n    return a + b\n"),
    ),
    GateCase(
        name="only_medium_findings",
        expected_block=False,
        note="A generic 20+ char api_key assignment is medium, not critical",
        setup=lambda d: _write(d, "app.py", 'api_key = "abcdefghijklmnopqrstuvwx"\n'),
    ),
    GateCase(
        name="only_high_findings",
        expected_block=False,
        note="A Slack token alone is high, not critical — current gate only blocks on critical",
        setup=lambda d: _write(d, "notify.py", 'SLACK_TOKEN = "xoxb-1234567890-abcdefghij"\n'),
    ),
    GateCase(
        name="dockerfile_missing_user_only",
        expected_block=False,
        note="dockerfile_no_user is medium — a real repo without USER shouldn't block every PR",
        setup=lambda d: _write(d, "Dockerfile", 'FROM python:3.12-slim\nCOPY . /app\nCMD ["python", "app.py"]\n'),
    ),
]


def _run_case(monkeypatch, tmp_path: Path, case: GateCase) -> GateResult:
    repo_dir = tmp_path / case.name
    repo_dir.mkdir()
    case.setup(repo_dir)

    # Wire the mocked, always-infected clamd for every case — cases that
    # don't plant EICAR simply won't have anything for it to flag, same
    # as a real clamd instance scanning a directory with no malware in it.
    monkeypatch.setattr(vs_mod.settings, "CLAMD_HOST", "clamd.internal")
    monkeypatch.setattr(vs_mod.clamd, "ClamdNetworkSocket", lambda **kw: _FakeClamdEicarAware())

    severities: list[str] = []
    severities += [f.severity for f in SecretScanner().scan(repo_dir)]
    severities += [f.severity for f in ConfigSecurityScanner().scan(repo_dir)]
    severities += ["critical" for _ in VirusScanner().scan_directory(repo_dir)]

    risk = RiskScorer().score(severities)

    class _R:
        counts_by_severity = risk.counts_by_severity

    actual_block = security_gate_should_block(_R())
    return GateResult(case=case, actual_block=actual_block, severities_found=severities)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_security_gate_case(monkeypatch, tmp_path, case: GateCase):
    result = _run_case(monkeypatch, tmp_path, case)
    assert result.actual_block == case.expected_block, (
        f"{case.name}: expected block={case.expected_block}, got {result.actual_block}. "
        f"Severities found: {result.severities_found or 'none'}. {case.note}"
    )


def test_benchmark_report(monkeypatch, tmp_path, capsys):
    """Not a correctness assertion on its own (test_security_gate_case
    already provides that, per-case, with a useful failure message) —
    this produces the human-readable summary table for `pytest -s`.
    """
    results = [_run_case(monkeypatch, tmp_path, c) for c in CASES]

    lines = [
        "",
        "Security Gate Benchmark",
        "=" * 72,
        f"{'case':<32}{'expected':<12}{'actual':<12}{'result'}",
        "-" * 72,
    ]
    for r in results:
        lines.append(
            f"{r.case.name:<32}{str(r.case.expected_block):<12}{str(r.actual_block):<12}"
            f"{'PASS' if r.passed else 'FAIL'}"
        )
    passed = sum(1 for r in results if r.passed)
    lines.append("-" * 72)
    lines.append(f"{passed}/{len(results)} passed")
    print("\n".join(lines))

    assert passed == len(results)
