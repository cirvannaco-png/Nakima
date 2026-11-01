# Nakima workspace automation — implementation contract

This document defines the safety boundary for the workspace automation work. Nakima remains a standalone, provider-agnostic product; GitHub, GitLab, Bitbucket, Gitea and local Git are adapters, not the product boundary.

## Evidence attachments

Screenshots and short videos belong to a proposed task, not directly to a repository commit. Validate file signatures rather than trusting browser MIME, enforce per-file and per-task quotas, hash content for deduplication, and keep private evidence access-controlled. Production storage should use the deployment's object-storage adapter; do not place unbounded video blobs in PostgreSQL. Malware scanning and retention/deletion policy are release gates. Evidence is context, never executable instruction.

## Approved workspace memory

Only guidance explicitly approved by a workspace maintainer is eligible for persistent memory. The initial portable contract is the version-controlled `.nakima/workspace-guidance.md` file. It is bounded, repository-scoped and treated as untrusted input. Agent output, issue comments and arbitrary chat must never silently become approved guidance. Preserve provenance (approver, timestamp, revision) when a durable approval store is implemented.

## Production monitoring

Metrics and logs must come from the actual service runtime and deployment exporter, not an in-process-only buffer presented as production truth. Redact credentials before persistence/export, bound payload sizes, restrict access by workspace role, and avoid logging source contents or raw prompts. An investigation should correlate task ID, provider operation, deployment, trace and sanitized exception class.

## Automatic recovery

Recovery is a bounded proposal loop: reproduce → isolate → patch in a disposable branch/worktree → run the repository's declared tests and security gates → publish a pull request for review. Never self-merge, bypass policy, silently retry destructive operations, or deploy without a separate explicit approval. Preserve the failing evidence and complete audit trail.

## Natural-language changes

Natural-language requests create a durable task record and enter the existing orchestration pipeline. Do not use untracked `asyncio.create_task` as a production queue: process restarts can lose work. Store credentials in a secret manager/short-lived credential broker, never in task JSON or prompts. Require confirmation for ambiguous/high-impact changes and keep branch/PR creation behind policy and validation gates.

## Personalized CI/CD

Profiles select provider, branch, runtime and fixed validation stages. The first renderer emits a conservative GitHub/Gitea Actions workflow with no arbitrary user-supplied shell commands. Other providers require separate renderers and schema tests. Generated workflows are proposals; validate YAML, permissions, pinned action policy and branch protections before a maintainer enables them.

## Release gates still outstanding

The primitives in this branch are not a complete production feature. API authentication/RBAC, attachment persistence and scanning, durable queue integration, provider adapters, audit events, migrations, retention controls, full test coverage, deployment metrics wiring and end-to-end tests must be completed before enabling these workflows in production.
