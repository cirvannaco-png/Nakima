# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.x (latest) | ✅ |
| < 1.0 | ❌ |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

To report a security vulnerability, open a [GitHub Security Advisory](https://github.com/cirvannaco-png/Nakima/security/advisories/new) or contact the maintainers privately via GitHub.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We aim to acknowledge reports within 48 hours and provide a fix within 14 days for critical issues.

## Security Measures

- All dependencies are pinned to exact versions and audited weekly via Dependabot
- Bandit SAST runs on every push via CI
- Trivy container scanning runs on every Docker build
- The sandbox executor runs with `--network none` — no outbound connectivity
- SSRF guard rejects all private/cloud-metadata IP ranges
- Webhook signatures are HMAC-SHA256 verified on every request
- No secrets are stored in the repository or Docker images

See [docs/SECURITY.md](docs/SECURITY.md) for the full security architecture.
