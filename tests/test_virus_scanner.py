"""Tests for security/virus_scanner.py. clamd itself isn't available in
this environment (it's a system daemon, not something pip can install and
run) — see the module's own docstring for the honest statement of what
that means: the client-protocol logic here is real and tested against a
mocked clamd client with realistic response shapes; the actual
malware-detection engine is not exercised by these tests. Before trusting
this in production, run the EICAR check documented in
security/virus_scanner.py against a real clamd.
"""

import clamd as clamd_mod
import pytest

import security.virus_scanner as vs_mod
from security.virus_scanner import VirusScanner, VirusScannerUnavailable


class _FakeClamd:
    def __init__(self, ping_error=None, instream_result=None, instream_error=None):
        self._ping_error = ping_error
        self._instream_result = instream_result if instream_result is not None else {"stream": ("OK", None)}
        self._instream_error = instream_error
        self.instream_calls = 0

    def ping(self):
        if self._ping_error:
            raise self._ping_error

    def instream(self, buf):
        self.instream_calls += 1
        if self._instream_error:
            raise self._instream_error
        return self._instream_result


def _make_scanner(monkeypatch, fake_client=None, configured=True):
    monkeypatch.setattr(vs_mod.settings, "CLAMD_HOST", "clamd.internal" if configured else None)
    if fake_client is not None:
        monkeypatch.setattr(vs_mod.clamd, "ClamdNetworkSocket", lambda **kw: fake_client)
    return VirusScanner()


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------


def test_scan_unavailable_when_not_configured(monkeypatch):
    scanner = _make_scanner(monkeypatch, configured=False)
    result = scanner.scan(b"hello")
    assert result.status == "unavailable"
    assert scanner.is_configured() is False


def test_scan_unavailable_when_ping_fails(monkeypatch):
    fake = _FakeClamd(ping_error=clamd_mod.ConnectionError("refused"))
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    result = scanner.scan(b"hello")
    assert result.status == "unavailable"
    assert "unreachable" in result.detail


def test_scan_clean_file(monkeypatch):
    fake = _FakeClamd(instream_result={"stream": ("OK", None)})
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    result = scanner.scan(b"hello world")
    assert result.status == "clean"
    assert fake.instream_calls == 1


def test_scan_infected_file_reports_threat_name(monkeypatch):
    fake = _FakeClamd(instream_result={"stream": ("FOUND", "Eicar-Test-Signature")})
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    result = scanner.scan(b"fake eicar content")
    assert result.status == "infected"
    assert result.threat_name == "Eicar-Test-Signature"


def test_scan_oversized_file_errors_without_calling_clamd(monkeypatch):
    fake = _FakeClamd()
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    monkeypatch.setattr(vs_mod, "_MAX_SCAN_BYTES", 10)
    result = scanner.scan(b"x" * 100)
    assert result.status == "error"
    assert fake.instream_calls == 0


def test_scan_buffer_too_long_from_clamd_itself(monkeypatch):
    fake = _FakeClamd(instream_error=clamd_mod.BufferTooLongError("too big"))
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    result = scanner.scan(b"hello")
    assert result.status == "error"


def test_scan_unexpected_response_shape_is_error_not_crash(monkeypatch):
    fake = _FakeClamd(instream_result={"stream": ("WEIRD", "???")})
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    result = scanner.scan(b"hello")
    assert result.status == "error"


# ---------------------------------------------------------------------------
# scan_directory()
# ---------------------------------------------------------------------------


def test_scan_directory_raises_when_not_configured(monkeypatch, tmp_path):
    scanner = _make_scanner(monkeypatch, configured=False)
    with pytest.raises(VirusScannerUnavailable):
        scanner.scan_directory(tmp_path)


def test_scan_directory_raises_when_ping_fails(monkeypatch, tmp_path):
    fake = _FakeClamd(ping_error=clamd_mod.ConnectionError("refused"))
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    with pytest.raises(VirusScannerUnavailable):
        scanner.scan_directory(tmp_path)


def test_scan_directory_finds_infected_file(monkeypatch, tmp_path):
    (tmp_path / "clean.txt").write_text("hello")
    (tmp_path / "bad.txt").write_text("eicar-like content")

    class _SelectiveFakeClamd(_FakeClamd):
        def instream(self, buf):
            self.instream_calls += 1
            content = buf.read()
            if b"eicar" in content:
                return {"stream": ("FOUND", "Eicar-Test-Signature")}
            return {"stream": ("OK", None)}

    scanner = _make_scanner(monkeypatch, fake_client=_SelectiveFakeClamd())
    findings = scanner.scan_directory(tmp_path)

    assert len(findings) == 1
    assert findings[0].file_path == "bad.txt"
    assert findings[0].threat_name == "Eicar-Test-Signature"


def test_scan_directory_skips_git_dir(monkeypatch, tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("eicar")

    class _AlwaysInfected(_FakeClamd):
        def instream(self, buf):
            self.instream_calls += 1
            return {"stream": ("FOUND", "Eicar-Test-Signature")}

    fake = _AlwaysInfected()
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    findings = scanner.scan_directory(tmp_path)

    assert findings == []
    assert fake.instream_calls == 0


def test_scan_directory_skips_empty_files(monkeypatch, tmp_path):
    (tmp_path / "empty.txt").write_text("")

    fake = _FakeClamd()
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    scanner.scan_directory(tmp_path)

    assert fake.instream_calls == 0


def test_scan_directory_stops_if_clamd_disappears_mid_scan(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")

    class _DisappearingClamd(_FakeClamd):
        def instream(self, buf):
            self.instream_calls += 1
            raise clamd_mod.ConnectionError("connection reset")

    fake = _DisappearingClamd()
    scanner = _make_scanner(monkeypatch, fake_client=fake)
    with pytest.raises(VirusScannerUnavailable, match="mid-scan"):
        scanner.scan_directory(tmp_path)
