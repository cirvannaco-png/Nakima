"""Dynamic Security Testing (DAST) — observational checks against a live,
already-running target URL. Deliberately does NOT send attack payloads,
attempt authentication bypass, fuzz inputs, or probe arbitrary paths —
see security/nsil.py's module docstring and the conversation that scoped
this (Penetration Testing Simulator is explicitly not built here, for
reasons that have nothing to do with implementation difficulty).

Everything this module does is equivalent to what a browser's dev tools,
`curl -I`, or an online SSL-checker already exposes about a public URL:
response headers, cookie flags, CORS policy, TLS/certificate validity,
and whether a 404 page leaks a stack trace. Two requests total per scan
(the root path, and one deliberately-missing path to check error-page
behavior) — no crawling, no parameter fuzzing, no authentication attempts.

Because this does make a real outbound request from Nakima's own server
to a caller-supplied URL, it resolves the hostname first and refuses
private/loopback/link-local/reserved/multicast addresses (see
_unsafe_target_reason) — otherwise the scanner itself would be an SSRF
oracle against Nakima's own network. Redirects aren't followed for the
same reason: a safe-looking URL could redirect somewhere the check above
never validated.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from security.ssrf_guard import unsafe_target_reason

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0
_PROBE_PATH = "/__nakima_dast_probe_nonexistent__"

# Substrings that show up in real stack-trace / debug-error output across
# common stacks. A hit means the error page is leaking implementation
# details (file paths, framework internals, sometimes query text) to
# anyone who requests a bad URL — genuinely useful to know, and detecting
# it requires no attack payload, just requesting a path that doesn't exist.
_STACK_TRACE_MARKERS = [
    r"Traceback \(most recent call last\)",
    "at java.",
    "Microsoft.AspNetCore",
    "System.Exception",
    "Whitelabel Error Page",
    "django.core.exceptions",
    "Warning: mysql_",
    "ORA-[0-9]{5}",
    "PostgreSQL.*ERROR",
]
_STACK_TRACE_PATTERN = re.compile("|".join(_STACK_TRACE_MARKERS), re.IGNORECASE)

_SESSION_LIKE_COOKIE = re.compile(r"(session|auth|token|sid)", re.IGNORECASE)


@dataclass
class DASTFinding:
    rule: str
    severity: str
    detail: str


class DASTScanner:
    async def scan(self, target_url: str) -> list[DASTFinding]:
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return [
                DASTFinding(
                    rule="dast_invalid_target",
                    severity="low",
                    detail=f"'{target_url}' isn't an http(s) URL — nothing to scan.",
                )
            ]

        unsafe_reason = unsafe_target_reason(parsed.hostname)
        if unsafe_reason:
            return [
                DASTFinding(
                    rule="dast_target_refused",
                    severity="low",
                    detail=f"Refusing to scan {target_url}: {unsafe_reason}. DAST makes a real outbound "
                    "request from Nakima's own server — pointing it at a private/loopback/link-local "
                    "address would turn the scanner into a way to probe Nakima's own internal network "
                    "rather than the target application.",
                )
            ]

        findings: list[DASTFinding] = []

        if parsed.scheme == "http":
            findings.append(
                DASTFinding(
                    rule="dast_no_tls",
                    severity="high",
                    detail=f"Target is served over plain HTTP ({target_url}), not HTTPS.",
                )
            )

        try:
            # follow_redirects=False: a safe root URL that redirects to an
            # internal address would otherwise let the actual GET happen
            # somewhere the check above never validated. A redirect itself
            # isn't scanned further — only the target the caller gave us.
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
                root_response = await client.get(target_url)
                findings.extend(self._check_headers(root_response))
                findings.extend(self._check_cookies(root_response))

                probe_response = await client.get(target_url.rstrip("/") + _PROBE_PATH)
                findings.extend(self._check_error_leakage(probe_response))
        except httpx.RequestError as e:
            findings.append(
                DASTFinding(
                    rule="dast_target_unreachable",
                    severity="medium",
                    detail=f"Could not reach {target_url}: {type(e).__name__}: {e}. This includes TLS/"
                    "certificate failures (httpx surfaces those as a ConnectError, not a distinct type).",
                )
            )

        return findings

    def _check_headers(self, response: httpx.Response) -> list[DASTFinding]:
        findings = []
        headers = {k.lower(): v for k, v in response.headers.items()}

        if response.url.scheme == "https" and "strict-transport-security" not in headers:
            findings.append(
                DASTFinding(
                    rule="dast_missing_hsts",
                    severity="medium",
                    detail="No Strict-Transport-Security header — browsers won't enforce HTTPS on repeat visits.",
                )
            )

        if headers.get("x-content-type-options", "").lower() != "nosniff":
            findings.append(
                DASTFinding(
                    rule="dast_missing_content_type_options",
                    severity="low",
                    detail="Missing 'X-Content-Type-Options: nosniff' — browsers may MIME-sniff responses.",
                )
            )

        has_frame_protection = "x-frame-options" in headers or "frame-ancestors" in headers.get(
            "content-security-policy", ""
        )
        if not has_frame_protection:
            findings.append(
                DASTFinding(
                    rule="dast_missing_frame_protection",
                    severity="medium",
                    detail="No X-Frame-Options or CSP frame-ancestors — page can be framed (clickjacking risk).",
                )
            )

        if "content-security-policy" not in headers:
            findings.append(
                DASTFinding(
                    rule="dast_missing_csp",
                    severity="low",
                    detail="No Content-Security-Policy header set.",
                )
            )

        acao = headers.get("access-control-allow-origin", "")
        acac = headers.get("access-control-allow-credentials", "").lower() == "true"
        if acao == "*" and acac:
            findings.append(
                DASTFinding(
                    rule="dast_dangerous_cors",
                    severity="high",
                    detail="Access-Control-Allow-Origin: * combined with Access-Control-Allow-Credentials: "
                    "true — any origin can make credentialed requests. Most browsers reject this "
                    "combination, but some don't, and it signals a misconfigured CORS policy either way.",
                )
            )

        server = headers.get("server", "")
        if re.search(r"/\d", server):  # e.g. "Apache/2.4.41", "nginx/1.18.0" — a version number present
            findings.append(
                DASTFinding(
                    rule="dast_server_version_disclosed",
                    severity="low",
                    detail=f"Server header discloses a specific version: {server!r}.",
                )
            )

        return findings

    def _check_cookies(self, response: httpx.Response) -> list[DASTFinding]:
        findings = []
        for cookie_header in response.headers.get_list("set-cookie"):
            name = cookie_header.split("=", 1)[0].strip()
            attrs = cookie_header.lower()
            if not _SESSION_LIKE_COOKIE.search(name):
                continue  # only flag cookies that look like they carry auth/session state
            if "secure" not in attrs and response.url.scheme == "https":
                findings.append(
                    DASTFinding(
                        rule="dast_cookie_missing_secure",
                        severity="medium",
                        detail=f"Cookie '{name}' looks session-related but lacks the Secure flag over HTTPS.",
                    )
                )
            if "httponly" not in attrs:
                findings.append(
                    DASTFinding(
                        rule="dast_cookie_missing_httponly",
                        severity="medium",
                        detail=f"Cookie '{name}' looks session-related but lacks HttpOnly — readable by JS "
                        "(XSS would be able to steal it).",
                    )
                )
            if "samesite" not in attrs:
                findings.append(
                    DASTFinding(
                        rule="dast_cookie_missing_samesite",
                        severity="low",
                        detail=f"Cookie '{name}' has no SameSite attribute (CSRF exposure depends on other "
                        "mitigations being present).",
                    )
                )
        return findings

    def _check_error_leakage(self, response: httpx.Response) -> list[DASTFinding]:
        if _STACK_TRACE_PATTERN.search(response.text[:5000]):
            return [
                DASTFinding(
                    rule="dast_stack_trace_leak",
                    severity="high",
                    detail=f"Requesting a nonexistent path ({_PROBE_PATH}) returned what looks like a "
                    "framework stack trace or debug error page — implementation details are exposed "
                    "to anyone who hits a bad URL.",
                )
            ]
        return []
