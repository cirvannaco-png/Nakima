# Known Gaps — Nakima Lab / Sandbox / Self-Healing v0.1

> **Release status:** not production-ready. The Lab is a scaffold, not an operational security boundary. See issue #94.

Explicit per Directive: undocumented gaps are liabilities. This is what's
real vs. stubbed right now.

## Database identity and tenant foundation

- Migration `0013` adds provider-neutral `provider_installations` and links
  the existing integer-keyed `repositories` rows to an internal installation
  ID. External installation IDs are strings, unique within each provider.
- Existing repository rows remain unattached and Lab-opted-out until trusted
  provider metadata is synchronized. The database CHECK requires a complete
  consent record before opt-in.
- Migration `0014` adds `sandbox_runs`, `run_reviews`, and
  `model_candidate_fixes`. Runs retain the canonical repository ID and
  installation snapshot using restrictive FKs. PostgreSQL triggers verify
  active installation ownership and synthetic-injection consent at creation.
- Migration `0015` adds explicit OIDC principal memberships per provider
  installation, with role, grantor, and revocation audit. Migration `0016`
  expands review identity storage to the complete issuer + subject.
- The old `db/schema.sql` UUID repository draft is non-executable and is not
  in the Alembic chain. Do not apply it.

## API exposure and authorization blocker

- The Lab FastAPI app in `orchestrator/main.py` remains unmounted and is not
  run by the current Compose services. The production Dockerfile starts only
  `api.router:app`; the Compose `sandbox` service only builds a runner image.
- Lab requests now require OIDC bearer JWT verification against a configured
  issuer, audience and HTTPS JWKS endpoint. Membership binds exact
  `(issuer, subject)` identities to one provider installation. Roles separate
  run creation, read access and review. Global operator actions require a
  separate immutable-subject allowlist.
- Caller-supplied UUID repository/organization IDs and
  `reviewer_user_id` have been removed. Reviewer identity is derived from the
  verified principal and stored as issuer + subject.
- Configure `LAB_OIDC_ISSUER`, `LAB_OIDC_AUDIENCE`,
  `LAB_OIDC_JWKS_URL`, and `LAB_OIDC_ADMIN_SUBJECTS` only after choosing an
  identity provider. No provider is selected or configured in this branch.
- The run-creation endpoint deliberately returns 503 even for authorized
  callers. It does not create a run until the trusted-host clone, immutable
  archive transfer, isolated runner, typed result contract and full lifecycle
  are implemented. Read and review endpoints use durable records and roles.
- Installation deletion revokes memberships; suspension blocks access while
  preserving memberships for an explicit unsuspend. Webhook events never
  auto-provision end-user membership.

## Remaining P0 engineering work

- The trusted-host source-bundle building block now verifies the exact commit
  through the GitHub API, fetches a tarball using a repository-scoped
  `contents:read` token, never forwards that token to codeload, computes a
  SHA-256 digest, and rejects path traversal, links, special files, duplicate
  paths and archive-size bombs. It deliberately rejects repositories that
  contain symlinks until a separately tested safe-link policy exists.
- Still required: wire the helper to an authenticated host-side orchestration
  lifecycle, obtain the narrowly scoped token (PR #95), pass only the archive
  and expected digest as read-only input to the container, and make the
  runner verify/extract that archive. Never pass a clone URL or credential to
  the network-isolated container.
- One authoritative sandbox image, tag and entrypoint. The current image
  requested by the Lab scaffold does not match the image built by CI.
- Typed result schema and versioned container output; bounded polling,
  timeout/cancellation, terminal-state persistence, log capture and teardown.
- Connect the lifecycle to the durable run/candidate/review tables. The
  schema exists, but no safe execution lifecycle currently creates or completes
  runs.
- Wire `diagnose_failure` and `generate_candidate_fix` to provider APIs.
  Apply every candidate patch to a clean worktree before tests; retain commit
  SHA, test logs/results and per-candidate evidence.
- Validate tenant isolation and access revocation through the actual Lab API
  against a selected OIDC provider. The current JWT/membership primitives
  have unit tests but have not been verified with a real provider or deployed
  identity configuration.
- Test the full path against controlled Nakima and Midas-Touch CI failures
  before allowing customer repositories.

## Explicitly out of scope for this pass

- Kubernetes / distributed job queue — no scale signal justifies this yet
  per the Cardinal Rule. Single-host Docker orchestration is correct until
  concurrent run volume says otherwise.
- Automated pattern_memory promotion — stays manual/weekly by design (see
  NEIS_LEARNING_POLICY.md). Do not automate before you have a track record
  of what a bad promotion looks like.
- Cross-provider deploy migration, multi-cloud deploy targets — separate
  workstream, not touched by this sandbox/self-healing work.

## Security items requiring sign-off before first live test with real user repos

- Verify the sandbox container truly has `network_mode="none"` end-to-end,
  with no sidecar, DNS or host-mounted credential path that leaks access.
- Verify the repository credential is read-only and restricted to exactly one
  repository at the provider API level. The ordinary GitHub workflow token
  remains a separate PR #95 integration gate.
- Exercise the PostgreSQL active-installation and synthetic-consent triggers
  with attempted bypasses. The migration integration test covers the current
  denial/allowance path; adversarial tests still need to cover reassignment,
  suspension, concurrent changes and deletion.
- Verify OIDC issuer/audience/key rotation, operator bootstrap, role changes,
  revoked membership behavior and concurrent review requests with the chosen
  production identity provider.
