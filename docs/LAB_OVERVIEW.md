# Nakima Lab & Sandbox — Current Engineering Status

## Status: foundation only; not ready for live repository execution

The Lab is an intended isolated environment for reproducing CI failures,
scanning dependencies, proposing fixes, validating candidate patches, and
presenting results for human review. The current code is a partial scaffold,
not a functioning end-to-end security boundary. Do not enable it against
production or customer repositories.

## Canonical identity and persistence

The existing application schema is authoritative:

- `repositories.id` is the canonical integer repository primary key.
- `tasks.repository_id` references that integer key.
- `provider_installations.id` is the internal provider-tenant key. Its
  external installation identifier is stored as text with a unique
  `(provider, external_installation_id)` constraint, so GitHub, GitLab, and
  future providers do not impose their external ID formats on Nakima.
- The GitHub provider adapter now consumes signed `installation` and
  `installation_repositories` webhooks. It upserts installation/account
  metadata, associates repository IDs with the existing canonical rows,
  handles rename/add/remove events, marks suspensions/deletions inactive, and
  revokes Lab consent on suspension, deletion, removal, or reassignment.
  These events do not mint or receive an automation token.
- `repositories.provider_installation_id` associates a repository with its
  provider installation. Existing rows remain unattached until verified.
- `provider_installation_memberships` binds an exact OIDC `(issuer, subject)`
  pair to one provider installation and one explicit role. Membership grants
  are allowlisted by a global Lab operator; membership revocation is audited.
  Email addresses and caller-supplied user IDs are not authorization keys.
- Lab consent is stored on the canonical repository row. Legacy rows default
  to opted out. A database CHECK constraint prevents opt-in unless the
  installation, timestamp, actor, and consent-version are all present.

Migrations `0013`–`0016` define provider installation ownership, repository
consent, durable runs/candidates/reviews, installation membership, and
full OIDC reviewer-subject storage. A run keeps a snapshot of the owning
installation using separate restrictive foreign keys; a PostgreSQL trigger
checks the current repository-to-installation link at run creation. The old
`db/schema.sql` UUID-based repository schema was never part of the Alembic
chain and is explicitly marked deprecated and non-executable. Do not apply it.

## Target lifecycle (not yet implemented end to end)

1. Resolve the canonical repository and provider installation from trusted,
   verified provider metadata.
2. Obtain a narrowly scoped, read-only credential for that one repository.
3. Fetch the exact commit via the GitHub API on the trusted host and verify
   GitHub's returned commit SHA. The new `lab/source_bundle.py` helper then
   downloads the archive without forwarding credentials to codeload, records
   a SHA-256 digest, and rejects unsafe tar entries during extraction.
4. Transfer only the immutable archive and digest into a network-isolated
   container. Do not give the sandbox a credential, clone URL or network access.
4. Run baseline checks and diagnostics.
5. Generate candidate patches through configured provider adapters.
6. Apply each candidate to its own clean worktree before running the full
   validation suite. Record per-candidate evidence.
7. Persist a typed result against the canonical repository and run identity.
8. Present the result for human review. PR creation remains a separate,
   explicit action; no auto-push or auto-merge.

## Confirmed blockers

- `orchestrator/main.py` is a separate FastAPI application and is not
  mounted by `api/router.py` or run as a service in the current
  `docker-compose.yml`. The current production Dockerfile starts only
  `api.router:app`. Lab endpoints are therefore not part of the deployed
  Nakima API.
- Do not expose or mount that app yet. The Lab routes now require OIDC bearer
  verification and installation-scoped roles, use the canonical integer
  repository ID, and derive reviewer identity from the verified principal.
  However, this app is still a separate unmounted service, and end-to-end
  authentication/authorization has not been validated against a selected
  production identity provider.
- The Lab API now uses `repositories.id` (integer), reads durable run/review
  rows, and authorizes those operations against active installation
  memberships. Run creation intentionally returns 503: there is no complete
  runner lifecycle yet, so no run is falsely marked queued or accepted.
- The installation webhook adapter is GitHub-specific (as intended for the
  current integration). The generic installation model is provider-neutral,
  but other providers still need their own webhook/sync adapters. Normal
  GitHub issue/push/PR events now require a synchronized active installation
  and exact repository-ID ownership before the workflow-token request. The
  separate workflow token itself remains unscoped until PR #95 is integrated.
- The sandbox container is launched with `network_mode="none"`, while the
  current entrypoint still attempts to clone from GitHub inside the container.
  `lab/source_bundle.py` now provides the trusted-host pinned archive and
  safe-extraction building block, but no orchestrator route invokes it and
  the runner entrypoint has not yet been converted to consume the archive.
  The two sides must be integrated before the Lab can run.
- The orchestrator's requested image name does not match the image/tag built
  by CI; the Lab image and entrypoint need one authoritative build path.
- `diagnose_failure` and `generate_candidate_fix` are not wired to real
  provider calls. The current candidate loop also needs to apply each patch
  before testing it; otherwise it can validate the unchanged baseline.
- The ORM/migrations define `sandbox_runs`, `run_reviews`, and
  `model_candidate_fixes`. Runs retain a canonical repository ID and an
  installation snapshot; database triggers check active ownership and
  synthetic-injection consent at insert/update. The Lab routes can read and
  review durable rows under installation-scoped roles, but no safe runner
  lifecycle creates and completes those rows yet.
- Container completion, malformed result handling, timeouts, cancellation,
  teardown and terminal-state persistence are not complete.

See `docs/known-gaps.md` and issue #94 for the implementation sequence and
acceptance gates.

## Authentication and deployment gate

The Lab API now has a generic OIDC verifier (issuer, audience, HTTPS JWKS),
an explicit operator subject allowlist, auditable installation-scoped
membership grants, role checks on run/read/review, and server-derived reviewer
identity. Configure these values from the chosen identity provider before
deployment:

- `LAB_OIDC_ISSUER`: exact issuer URL from the provider's OIDC metadata
- `LAB_OIDC_AUDIENCE`: audience/client identifier accepted by the Lab API
- `LAB_OIDC_JWKS_URL`: provider's HTTPS JSON Web Key Set endpoint
- `LAB_OIDC_ADMIN_SUBJECTS`: comma-separated immutable `sub` values allowed
  to administer installation memberships

No default issuer, audience, JWKS host, email-based identity, or automatic
membership is assumed. Keep the Lab service unmounted until
provider-backed login, operator provisioning, membership lifecycle and
end-to-end authorization tests pass.

## Safety rule

Until the blockers above are closed and functional, adversarial, tenant
isolation, credential-scope, timeout, teardown, and end-to-end tests pass,
Lab execution must remain disabled for live repositories.
