---
name: Nakima security push & vulnerability remediation
description: Key findings from remediating CVEs and pushing the Nakima repo to GitHub
---

## Summary
All Python packages in requirements.txt were pinned to latest secure versions (July 2026). The original 89 Dependabot alerts were all Python-ecosystem CVEs. After the fix, pnpm audit reports 0 npm vulnerabilities, but GitHub Dependabot shows ~108 alerts.

## Key finding: Dependabot count discrepancy
- `pnpm audit` uses the npm advisory database → **0 vulnerabilities** after fix
- GitHub Dependabot uses the GitHub Advisory Database (GHSA) → ~108 alerts
- The GHSA alerts come from the Replit workspace's Node.js build toolchain (Vite, Tailwind, esbuild, etc.) — dev-only transitive deps that don't ship to production
- These were NOT part of the original 89; they were always there but not visible until dependabot.yml enabled npm scanning

## What was fixed
- All Python packages pinned to latest secure versions: cryptography 45.0.3, fastapi 0.115.12, PyJWT 2.10.1, gitpython 3.1.44, etc.
- esbuild: 0.27.3 → 0.28.1 (GHSA-g7r4-m6w7-qqqr)
- js-yaml: forced to >=5.2.1 via pnpm override (GHSA-52cp-r559-cp3m)
- aquasecurity/trivy-action: @master → @0.30.0

## Dependabot config
`.github/dependabot.yml` added to enable automated weekly PRs for: pip, npm, github-actions, docker

## Python tooling unavailable
pip, pip-audit, python3 are not available in the NixOS Replit shell — use GitHub Actions CI for Python dependency auditing.

**Why:** NixOS environment doesn't install Python globally by default; it's inside the Docker/runtime.
