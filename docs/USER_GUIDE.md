# Nakima User Guide

## Getting Started

### 1 — Install the GitHub App

> Once Nakima is publicly launched, install it from [github.com/apps/nakima](https://github.com/apps/nakima).

During installation, select which repositories Nakima should have access to. Grant only the repositories you want automated — you can change this later in GitHub Settings → Applications.

### 2 — Open the Command Centre

Navigate to your Nakima deployment URL (or `http://localhost:8000` for self-hosted) to open the Command Centre dashboard. It shows:
- Active tasks (current issue → PR jobs)
- Repository health scores
- Security findings summary
- Recent decisions and events

### 3 — Trigger Automation

Nakima activates automatically when:
- A GitHub Issue is **opened** or **labeled** on an installed repository

You can also trigger manually via the API:
```bash
curl -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"repo_full_name": "owner/repo", "issue_number": 42, "github_token": "ghp_..."}'
```

---

## Working with Issues

Nakima reads the issue title and body to understand what needs to be done. Write clear, specific issues for best results:

**Good issue:**
```
Title: Add rate limiting to the /api/users endpoint

Body:
The /api/users endpoint has no rate limiting. Add a 100 req/min limit
per IP using slowapi. Return 429 with a Retry-After header when exceeded.

Acceptance criteria:
- Limit: 100 requests per minute per IP
- Response: 429 with Retry-After header
- Tests updated
```

**Less effective:**
```
Title: Fix the users thing
Body: It's too slow
```

---

## Understanding Task Stages

Watch task progress in the Command Centre or via `GET /api/v1/tasks/{task_id}`:

| Stage | What's happening |
|---|---|
| `pending` | Task queued, waiting to start |
| `running: intent` | NEIS reasoning classifying the issue |
| `running: plan` | AI generating implementation steps |
| `running: implement` | Generating code changes |
| `running: security` | NSIL scanning the generated diff |
| `running: validate` | Running tests, linting, coverage |
| `running: quality` | Quality gate evaluation |
| `running: pr` | Opening the pull request on GitHub |
| `success` | PR opened — link in task result |
| `failed` | An error occurred — check `error` field |

---

## Reviewing Pull Requests

Nakima opens PRs from a branch named `nakima/issue-{number}`. Each PR includes:

- **Description** — What was done and why, linked to the original issue
- **Test results** — Summary of what passed
- **Security scan** — Any findings from the NSIL scan
- **Quality gate** — Whether test coverage was maintained
- **Decision log** — The reasoning chain NEIS used

Review the PR as you would any human-authored PR. Merge it, request changes, or close it — Nakima won't re-open it.

---

## Security Scanning

### On-demand scan

```bash
curl -X POST http://localhost:8000/api/v1/security/owner%2Frepo/scan \
  -H "Content-Type: application/json" \
  -d '{
    "github_token": "ghp_...",
    "target_url": "https://your-app.example.com"
  }'
```

The `target_url` field triggers DAST (passive checks against your live deployment). Add `"run_pentest_simulator": true` for active pentest checks — Nakima will verify you own the target first.

### Viewing findings

```bash
curl http://localhost:8000/api/v1/security/owner%2Frepo/findings
```

Findings include a severity, rule ID, and detail. Re-scanning the same repo tracks which findings were resolved between scans.

---

## Engineering Reports

Generate a PDF report covering all decisions, events, and security findings:

```bash
curl -X POST http://localhost:8000/api/v1/intelligence/owner%2Frepo/report
curl http://localhost:8000/api/v1/intelligence/owner%2Frepo/report/latest --output report.pdf
```

---

## Uploading Context Documents

Give Nakima extra context about your project (architecture docs, API specs, design docs):

```bash
curl -X POST http://localhost:8000/api/v1/documents/owner%2Frepo/upload \
  -F "file=@architecture.pdf"
```

Supported formats: PDF, DOCX.

---

## Frequently Asked Questions

**Q: Nakima opened a PR but the tests fail. What do I do?**
A: Review the PR — the CI failure shows what's wrong. You can comment on the PR, close it, and open a new issue with more specific requirements. Nakima will try again.

**Q: Can Nakima modify files outside the issue scope?**
A: No. Nakima plans changes scoped to the issue description. It won't refactor unrelated code.

**Q: What languages does Nakima support?**
A: Python, TypeScript/JavaScript, and Go for code generation and validation. Repository analysis (AST, health scores) covers all languages tree-sitter parses.

**Q: Is my code sent to a third-party AI?**
A: If using GitHub Models (default), code snippets are sent to Microsoft Azure (GitHub's inference backend) subject to GitHub's privacy policy. For full data sovereignty, configure Nakima with a self-hosted model.

**Q: Can I disable automatic triggering?**
A: Yes — uninstall Nakima from specific repositories in GitHub Settings, or use label-based filtering (label issues with `nakima:skip` to exclude them).
