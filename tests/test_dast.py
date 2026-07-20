"""Tests for security/dast.py. The SSRF-guard tests use real IP literals
(no DNS needed, no network call happens since the guard runs before any
HTTP request). The header/cookie/error-leak tests monkeypatch
socket.getaddrinfo (to simulate a public-looking hostname) and
httpx.AsyncClient (to return controlled responses) — no real network
call anywhere in this file, same discipline as
tests/test_github_models_provider.py.
"""

import httpx
import pytest

import security.dast as dast_mod
from security.dast import DASTScanner


# ---------------------------------------------------------------------------
# SSRF guard — no network needed, IP literals resolve locally
# ---------------------------------------------------------------------------


async def test_invalid_scheme_is_rejected():
    findings = await DASTScanner().scan("ftp://example.com")
    assert len(findings) == 1
    assert findings[0].rule == "dast_invalid_target"


async def test_loopback_target_refused():
    findings = await DASTScanner().scan("http://127.0.0.1/")
    assert findings[0].rule == "dast_target_refused"
    assert "loopback" in findings[0].detail


async def test_private_ip_target_refused():
    findings = await DASTScanner().scan("http://10.0.0.5/")
    assert findings[0].rule == "dast_target_refused"


async def test_cloud_metadata_endpoint_refused():
    findings = await DASTScanner().scan("http://169.254.169.254/latest/meta-data/")
    assert findings[0].rule == "dast_target_refused"
    assert "link-local" in findings[0].detail


async def test_localhost_hostname_refused(monkeypatch):
    monkeypatch.setattr(dast_mod.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))])
    findings = await DASTScanner().scan("http://localhost/")
    assert findings[0].rule == "dast_target_refused"


async def test_unresolvable_hostname_refused(monkeypatch):
    import socket as real_socket

    def _raise(*a, **kw):
        raise real_socket.gaierror("Name or service not known")

    monkeypatch.setattr(dast_mod.socket, "getaddrinfo", _raise)
    findings = await DASTScanner().scan("http://this-does-not-resolve.invalid/")
    assert findings[0].rule == "dast_target_refused"
    assert "didn't resolve" in findings[0].detail


# ---------------------------------------------------------------------------
# Observational checks — public-looking target, mocked HTTP client
# ---------------------------------------------------------------------------


def _patch_public_dns(monkeypatch):
    monkeypatch.setattr(
        dast_mod.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, **kw):
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses):
    monkeypatch.setattr(dast_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(responses))


async def test_https_target_with_no_security_headers_flags_all_of_them(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(200, headers={}, text="hello", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(404, headers={}, text="not found", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    rules = {f.rule for f in findings}
    assert "dast_missing_hsts" in rules
    assert "dast_missing_content_type_options" in rules
    assert "dast_missing_frame_protection" in rules
    assert "dast_missing_csp" in rules


async def test_https_target_with_good_headers_has_no_header_findings(monkeypatch):
    _patch_public_dns(monkeypatch)
    good_headers = {
        "strict-transport-security": "max-age=63072000",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "content-security-policy": "default-src 'self'",
    }
    root = httpx.Response(200, headers=good_headers, text="hello", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(404, headers={}, text="not found", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    header_rules = {f.rule for f in findings if f.rule.startswith("dast_missing")}
    assert header_rules == set()


async def test_dangerous_cors_combination_flagged(monkeypatch):
    _patch_public_dns(monkeypatch)
    headers = {
        "strict-transport-security": "max-age=1",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "content-security-policy": "default-src 'self'",
        "access-control-allow-origin": "*",
        "access-control-allow-credentials": "true",
    }
    root = httpx.Response(200, headers=headers, text="hi", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(404, headers={}, text="nf", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    assert any(f.rule == "dast_dangerous_cors" for f in findings)


async def test_server_version_disclosure_flagged(monkeypatch):
    _patch_public_dns(monkeypatch)
    headers = {"server": "nginx/1.18.0"}
    root = httpx.Response(200, headers=headers, text="hi", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(404, headers={}, text="nf", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    assert any(f.rule == "dast_server_version_disclosed" for f in findings)


async def test_session_cookie_missing_flags_flagged(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(
        200,
        headers=[("set-cookie", "session_id=abc123; Path=/")],
        text="hi",
        request=httpx.Request("GET", "https://example.test/"),
    )
    probe = httpx.Response(404, headers={}, text="nf", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    rules = {f.rule for f in findings}
    assert "dast_cookie_missing_secure" in rules
    assert "dast_cookie_missing_httponly" in rules
    assert "dast_cookie_missing_samesite" in rules


async def test_non_session_cookie_not_flagged(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(
        200,
        headers=[("set-cookie", "theme=dark; Path=/")],
        text="hi",
        request=httpx.Request("GET", "https://example.test/"),
    )
    probe = httpx.Response(404, headers={}, text="nf", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    assert not any(f.rule.startswith("dast_cookie") for f in findings)


async def test_stack_trace_on_probe_path_flagged(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(200, headers={}, text="hi", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(
        500,
        headers={},
        text="Traceback (most recent call last):\n  File 'app.py', line 10\nZeroDivisionError",
        request=httpx.Request("GET", "https://example.test/x"),
    )
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    assert any(f.rule == "dast_stack_trace_leak" for f in findings)


async def test_clean_404_does_not_flag_stack_trace(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(200, headers={}, text="hi", request=httpx.Request("GET", "https://example.test/"))
    probe = httpx.Response(404, headers={}, text="Not Found", request=httpx.Request("GET", "https://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("https://example.test/")
    assert not any(f.rule == "dast_stack_trace_leak" for f in findings)


async def test_http_target_flags_no_tls(monkeypatch):
    _patch_public_dns(monkeypatch)
    root = httpx.Response(200, headers={}, text="hi", request=httpx.Request("GET", "http://example.test/"))
    probe = httpx.Response(404, headers={}, text="nf", request=httpx.Request("GET", "http://example.test/x"))
    _patch_client(monkeypatch, [root, probe])

    findings = await DASTScanner().scan("http://example.test/")
    assert any(f.rule == "dast_no_tls" for f in findings)


async def test_request_error_reported_as_unreachable(monkeypatch):
    _patch_public_dns(monkeypatch)

    class _RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, **kw):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(dast_mod.httpx, "AsyncClient", lambda **kw: _RaisingClient())

    findings = await DASTScanner().scan("https://example.test/")
    assert findings[0].rule == "dast_target_unreachable"
