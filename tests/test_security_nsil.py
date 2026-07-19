"""Tests for security/secret_scanner.py, config_scanner.py, risk_scoring.py,
and nsil.py. Scanners run against real files written to tmp_path — no
mocking of the logic that matters. NSIL's agent-backed scanners (SAST,
dependency audit) need Docker, which isn't available in this environment,
so SecurityIntelligenceLayer.scan() is expected to degrade gracefully and
those tests assert exactly that degradation rather than mocking Docker
away.
"""

from models.repository import Repository
from security.config_scanner import ConfigSecurityScanner
from security.nsil import SecurityIntelligenceLayer
from security.risk_scoring import RiskScorer
from security.secret_scanner import SecretScanner


# ---------------------------------------------------------------------------
# SecretScanner
# ---------------------------------------------------------------------------


def test_secret_scanner_finds_aws_key(tmp_path):
    (tmp_path / "settings.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    findings = SecretScanner().scan(tmp_path)
    assert any(f.pattern_name == "aws_access_key_id" for f in findings)


def test_secret_scanner_finds_github_pat_in_file(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=ghp_" + "a" * 36 + "\n")
    findings = SecretScanner().scan(tmp_path)
    assert any(f.pattern_name == "github_pat" for f in findings)


def test_secret_scanner_finds_private_key_block(tmp_path):
    (tmp_path / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----\n")
    findings = SecretScanner().scan(tmp_path)
    assert any(f.pattern_name == "private_key_block" for f in findings)


def test_secret_scanner_redacts_the_actual_value(tmp_path):
    (tmp_path / "settings.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    findings = SecretScanner().scan(tmp_path)
    finding = next(f for f in findings if f.pattern_name == "aws_access_key_id")
    assert "AKIAIOSFODNN7EXAMPLE" not in finding.redacted_preview
    assert finding.redacted_preview.startswith("AKIA")


def test_secret_scanner_skips_markdown(tmp_path):
    (tmp_path / "README.md").write_text("Example key: AKIAIOSFODNN7EXAMPLE\n")
    findings = SecretScanner().scan(tmp_path)
    assert findings == []


def test_secret_scanner_ignores_git_dir(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("AKIAIOSFODNN7EXAMPLE\n")
    findings = SecretScanner().scan(tmp_path)
    assert findings == []


def test_secret_scanner_clean_repo_has_no_findings(tmp_path):
    (tmp_path / "main.py").write_text("def hello():\n    return 'world'\n")
    assert SecretScanner().scan(tmp_path) == []


# ---------------------------------------------------------------------------
# ConfigSecurityScanner
# ---------------------------------------------------------------------------


def test_config_scanner_flags_dockerfile_without_user(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\nCOPY . .\nCMD [\"python\", \"app.py\"]\n")
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert any(f.rule == "dockerfile_no_user" for f in findings)


def test_config_scanner_does_not_flag_dockerfile_with_user(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim\nCOPY . .\nUSER appuser\nCMD [\"python\", \"app.py\"]\n"
    )
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert not any(f.rule == "dockerfile_no_user" for f in findings)


def test_config_scanner_flags_unpinned_base_image(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:latest\nUSER appuser\n")
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert any(f.rule == "dockerfile_unpinned_base_image" for f in findings)


def test_config_scanner_flags_secret_in_env(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim\nUSER appuser\nENV AWS_SECRET_ACCESS_KEY=" + "a" * 40 + "\n"
    )
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert any(f.rule == "dockerfile_secret_in_env" for f in findings)


def test_config_scanner_flags_pwn_request_pattern(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "on: pull_request_target\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
    )
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert any(f.rule == "workflow_pwn_request" for f in findings)


def test_config_scanner_flags_echoed_secret(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: echo ${{ secrets.API_KEY }}\n"
    )
    findings = ConfigSecurityScanner().scan(tmp_path)
    assert any(f.rule == "workflow_secret_echoed" for f in findings)


def test_config_scanner_clean_repo_has_no_findings(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\nUSER appuser\nCOPY . .\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n")
    assert ConfigSecurityScanner().scan(tmp_path) == []


def test_config_scanner_no_dockerfile_or_workflows_is_fine(tmp_path):
    assert ConfigSecurityScanner().scan(tmp_path) == []


# ---------------------------------------------------------------------------
# RiskScorer
# ---------------------------------------------------------------------------


def test_risk_scorer_clean_is_100():
    result = RiskScorer().score([])
    assert result.score == 100.0
    assert result.total_findings == 0


def test_risk_scorer_deducts_by_severity():
    result = RiskScorer().score(["critical", "high", "medium", "low"])
    assert result.score == 100 - 25 - 12 - 5 - 2
    assert result.counts_by_severity == {"critical": 1, "high": 1, "medium": 1, "low": 1}


def test_risk_scorer_floors_at_zero():
    result = RiskScorer().score(["critical"] * 10)
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# SecurityIntelligenceLayer (integration, real DB, no Docker available)
# ---------------------------------------------------------------------------


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_nsil_scan_degrades_gracefully_without_docker(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "security.nsil.SecurityAgent",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    (tmp_path / "settings.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    repo = await _make_repo(db_session)

    result = await SecurityIntelligenceLayer(db_session, repo.id).scan(tmp_path)

    assert "sast" in result.scanners_skipped
    assert "dependency_audit" in result.scanners_skipped
    assert "secret_detection" in result.scanners_run
    assert result.total_open == 1
    assert result.new_finding_count == 1


async def test_nsil_scan_persists_findings_and_reruns_cleanly(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "security.nsil.SecurityAgent",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    (tmp_path / "settings.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    repo = await _make_repo(db_session)
    nsil = SecurityIntelligenceLayer(db_session, repo.id)

    first = await nsil.scan(tmp_path)
    assert first.new_finding_count == 1
    assert first.resolved_finding_count == 0

    second = await nsil.scan(tmp_path)
    assert second.new_finding_count == 0
    assert second.resolved_finding_count == 0
    assert second.total_open == 1


async def test_nsil_scan_marks_fixed_findings_resolved(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "security.nsil.SecurityAgent",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    settings_file = tmp_path / "settings.py"
    settings_file.write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    repo = await _make_repo(db_session)
    nsil = SecurityIntelligenceLayer(db_session, repo.id)

    first = await nsil.scan(tmp_path)
    assert first.total_open == 1

    settings_file.write_text("# secret removed\n")
    second = await nsil.scan(tmp_path)

    assert second.resolved_finding_count == 1
    assert second.total_open == 0


async def test_nsil_reopens_a_previously_resolved_finding(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "security.nsil.SecurityAgent",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    settings_file = tmp_path / "settings.py"
    settings_file.write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")
    repo = await _make_repo(db_session)
    nsil = SecurityIntelligenceLayer(db_session, repo.id)

    await nsil.scan(tmp_path)
    settings_file.write_text("# secret removed\n")
    await nsil.scan(tmp_path)
    settings_file.write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")  # reintroduced
    third = await nsil.scan(tmp_path)

    assert third.new_finding_count == 0  # same fingerprint, reopened not re-created
    assert third.total_open == 1
