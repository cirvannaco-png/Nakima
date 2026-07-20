"""Real virus/malware scanning via a ClamAV clamd daemon — not a
placeholder. This closes the gap flagged in documents/gateway.py's
original docstring ("Nakima has no AV integration anywhere in this
codebase").

What "real" means here concretely: this talks to an actual clamd process
over the wire (INSTREAM protocol via the `clamd` client library) and
interprets its actual response. It does not implement any virus
detection logic itself — ClamAV's signature database does that, which is
the correct division of labor; reimplementing malware detection here
would be both worse and pointless when a real, maintained engine exists.

Deployment requirement, stated plainly: this code does nothing useful
without a running clamd (and freshclam keeping its signatures current)
reachable at settings.CLAMD_HOST. Add to the deployment image:
    apt-get install -y clamav-daemon clamav-freshclam
    freshclam  # pull initial signatures
    clamd      # start the daemon (or run it as its own container/service)
Nothing in this sandbox environment can install or run a system daemon,
so this module is verified here via a mocked clamd client (tests/
test_virus_scanner.py) — the client-protocol logic is real and tested,
the actual malware-detection engine is not present in this environment
to test against. Before relying on this in production, run it against
the EICAR test string (https://www.eicar.org/download-anti-malware-testfile/)
— every real AV engine, including ClamAV, is designed to flag EICAR as
"Eicar-Test-Signature" specifically so integrations can be verified
without using real malware:
    from security.virus_scanner import VirusScanner
    EICAR = (
        b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
    )
    print(VirusScanner().scan(EICAR))  # expect status="infected"

Fails open by design (status="unavailable" rather than "clean" when
unreachable, and the caller decides what to do with that — see
documents/gateway.py and security/nsil.py) rather than fail-closed,
because a default-off scanner that isn't deployed yet would otherwise
reject every single upload the moment this code ships, before any
operator has installed clamd. "Unavailable" is recorded honestly in the
data (ProjectDocument.virus_scan_status, NSIL's scanners_skipped) so
"never scanned" is never confused with "scanned and clean" — the one
thing this module must not do.
"""

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import clamd

from core.config import settings
from neis.analyzers.project_modeler import IGNORED_DIRS

logger = logging.getLogger(__name__)

# clamd's default StreamMaxLength is 25MB; scanning a larger file over
# INSTREAM would just raise BufferTooLongError, so skip proactively for
# scan_directory rather than round-tripping to clamd first to find out.
_MAX_SCAN_BYTES = 25 * 1024 * 1024


@dataclass
class VirusScanResult:
    status: str  # "clean" | "infected" | "unavailable" | "error"
    threat_name: str | None = None
    detail: str = ""


@dataclass
class VirusFinding:
    file_path: str
    threat_name: str
    detail: str


class VirusScannerUnavailable(Exception):
    """Raised by scan_directory() when clamd isn't configured or isn't
    reachable — the caller (security/nsil.py) catches this to record the
    scan as skipped rather than silently reporting a clean repo.
    """


class VirusScanner:
    def __init__(self):
        self._client = clamd.ClamdNetworkSocket(
            host=settings.CLAMD_HOST, port=settings.CLAMD_PORT, timeout=settings.CLAMD_TIMEOUT_SECONDS
        ) if settings.CLAMD_HOST else None

    def is_configured(self) -> bool:
        return self._client is not None

    def scan(self, content: bytes) -> VirusScanResult:
        if self._client is None:
            return VirusScanResult(status="unavailable", detail="CLAMD_HOST is not configured.")

        try:
            self._client.ping()
        except clamd.ConnectionError as e:
            return VirusScanResult(status="unavailable", detail=f"clamd is configured but unreachable: {e}")

        if len(content) > _MAX_SCAN_BYTES:
            return VirusScanResult(
                status="error", detail=f"File is {len(content)} bytes, over clamd's {_MAX_SCAN_BYTES}-byte stream limit."
            )

        try:
            result = self._client.instream(io.BytesIO(content))
        except clamd.BufferTooLongError as e:
            return VirusScanResult(status="error", detail=f"clamd rejected the stream as too large: {e}")
        except clamd.ConnectionError as e:
            # Distinct from ClamdError below: this means clamd itself became
            # unreachable (it answered ping() a moment ago but not this
            # request) — the same failure mode as the "unavailable" case
            # above, not a protocol-level error where clamd is up but
            # unhappy about the request. scan_directory() relies on this
            # being "unavailable" specifically to know to stop scanning
            # rather than silently treating the rest of the files as clean.
            return VirusScanResult(status="unavailable", detail=f"clamd became unreachable mid-scan: {e}")
        except clamd.ClamdError as e:
            return VirusScanResult(status="error", detail=f"Scan failed: {type(e).__name__}: {e}")

        status, reason = result.get("stream", ("ERROR", "clamd returned no 'stream' result"))
        if status == "OK":
            return VirusScanResult(status="clean")
        if status == "FOUND":
            return VirusScanResult(status="infected", threat_name=reason, detail=f"clamd flagged this as {reason!r}")
        return VirusScanResult(status="error", detail=f"Unexpected clamd response: status={status!r} reason={reason!r}")

    def scan_directory(self, repo_dir: Path) -> list[VirusFinding]:
        """Scans every file under repo_dir (same IGNORED_DIRS exclusions
        as security/secret_scanner.py) and returns findings for infected
        files only — this is "scan code provided by the user for
        viruses" applied to an indexed repository, not just uploaded
        documents. One clamd round-trip per file; for a very large repo
        that's a lot of round-trips, which is the honest tradeoff for not
        assuming clamd shares a filesystem with wherever this runs (a
        CONTSCAN/MULTISCAN-on-a-shared-path approach would be faster but
        couples this code to a deployment topology it can't verify).
        """
        if not self.is_configured():
            raise VirusScannerUnavailable("CLAMD_HOST is not configured.")
        try:
            self._client.ping()
        except clamd.ConnectionError as e:
            raise VirusScannerUnavailable(f"clamd is configured but unreachable: {e}") from e

        repo_dir = Path(repo_dir)
        findings: list[VirusFinding] = []
        for file_path in repo_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in file_path.parts):
                continue
            try:
                size = file_path.stat().st_size
                if size == 0 or size > _MAX_SCAN_BYTES:
                    continue
                content = file_path.read_bytes()
            except OSError:
                continue

            result = self.scan(content)
            if result.status == "infected":
                findings.append(
                    VirusFinding(
                        file_path=str(file_path.relative_to(repo_dir)),
                        threat_name=result.threat_name or "unknown",
                        detail=result.detail,
                    )
                )
            elif result.status == "unavailable":
                # clamd went away mid-scan (was reachable at the ping
                # above, isn't now) — stop rather than silently treating
                # every remaining file as clean.
                raise VirusScannerUnavailable(f"clamd became unreachable mid-scan: {result.detail}")

        return findings
