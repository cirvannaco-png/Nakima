# Nakima Security Guide

## Secrets Management

- **Never commit secrets.** All credentials live in `.env` (excluded from git via `.gitignore`).
- In production, use Docker secrets, AWS Secrets Manager, or GCP Secret Manager — not environment variables baked into images.
- The `.env.example` shows all required keys. Copy it, fill it in, keep it private.
- The GitHub private key (`.pem`) is mounted as a file volume; it is never baked into the Docker image.

## Webhook Authentication

Every request to `POST /github/webhook` is verified with `X-Hub-Signature-256` (HMAC-SHA256 over the raw body, keyed with `GITHUB_WEBHOOK_SECRET`). Requests with missing or invalid signatures are rejected with 403 before any processing begins.

## SSRF Prevention

All outbound HTTP requests that accept caller-supplied URLs (DAST, Pentest Simulator) pass through `security/ssrf_guard.py`, which rejects:
- RFC-1918 private ranges (10.x, 172.16-31.x, 192.168.x)
- Loopback (127.x, ::1)
- Link-local (169.254.x — AWS/GCP metadata endpoints)
- IPv6 unique-local (fc00::/7)
- Reserved TLDs

DNS lookups are re-checked against the same blocklist after resolution to prevent DNS rebinding attacks.

## Target Ownership Binding

Before DAST or pentest checks run against a `target_url`, `security/target_binding.py` verifies that the URL is associated with the supplied GitHub repository (checks repository homepage, GitHub Pages URL, and deployment records). This prevents Nakima from being used to scan unrelated targets.

## Execution Sandbox

Generated code is never executed on the host. `execution/sandbox.py` runs all code inside a Docker container with:
- `--network none` — no outbound internet
- `--memory 512m` — memory cap
- `--cpus 1` — CPU cap
- Read-only mount of code under test
- Short timeout (configurable via `BUILD_TIMEOUT`)

## Virus Scanning

Uploaded documents pass through ClamAV (`security/virus_scanner.py`) before storage. The scanner is fail-open when the ClamAV daemon is unavailable (upload proceeds, scan result recorded as `unavailable`) — configurable to fail-closed if required.

## Dependency Policy

- All Python dependencies are pinned to exact versions in `requirements.txt`.
- Dependabot is configured to open PRs for dependency updates.
- The CI pipeline runs `safety check` on every push.
- `bandit` runs SAST over the Nakima source on every push.
- Container images are scanned with Trivy in CI.
- Do not introduce transitive dependencies without pinning them.

## Authorization Model

Nakima currently trusts network-level access (no per-user authentication). For multi-tenant deployments:
- Place Nakima behind a reverse proxy with authentication (OAuth2 proxy, mTLS, IP allowlist)
- Each GitHub App installation is scoped to specific repositories — Nakima cannot access repositories it isn't installed on

## Audit Trail

Every automated action Nakima takes is recorded in:
- `engineering_decisions` — what was decided and why
- `engineering_events` — what files were changed, what tests were run, risk level
- `security_findings` — all security scan results with regression tracking

These tables are append-only and never modified post-creation.
