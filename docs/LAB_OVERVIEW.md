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
- Lab consent is stored on the canonical repository row. Legacy rows default
  to opted out. A database CHECK constraint prevents opt-in unless the
  installation, timestamp, actor, and consent-version are all present.

Migration `0013` adds only the provider-neutral installation and repository
consent foundation. Durable run, candidate, and review tables are a separate
next step and are not in the migration chain yet. The old `db/schema.sql`
UUID-based repository schema was never part of the Alembic chain and is now
explicitly marked deprecated and non-executable. Do not apply it.

## Target lifecycle (not yet implemented end to end)

1. Resolve the canonical repository and provider installation from trusted,
   verified provider metadata.
2. Obtain a narrowly scoped, read-only credential for that one repository.
3. Clone the exact pinned commit on the trusted host; transfer a verified,
   immutable source archive into a network-isolated container. Do not give the
   sandbox a credential or network access.
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
- Do not expose or mount that app yet: its request contract still accepts
  caller-supplied UUID repository/organization IDs, and the review endpoint
  accepts a caller-supplied reviewer ID. There is no authenticated Lab
  principal or tenant-membership authorization dependency. Exposing it as
  written would allow spoofed reviewer identities and unauthorized run
  requests.
- `orchestrator/main.py` also uses an in-memory run registry and contains
  unimplemented consent, clone-resolution, result-polling, and persistence
  functions. Its request contract does not yet use the canonical integer
  repository key.
- The installation webhook adapter is GitHub-specific (as intended for the
  current integration). The generic installation model is provider-neutral,
  but other providers still need their own webhook/sync adapters. Normal
  issue/push/PR events also still need to be bound to the stored installation
  row before any workflow token is minted.
- The sandbox container is launched with `network_mode="none"`, while the
  current entrypoint attempts to clone from GitHub inside the container.
  Those requirements contradict each other. Host-side clone and immutable
  transfer must replace in-container network access.
- The orchestrator's requested image name does not match the image/tag built
  by CI; the Lab image and entrypoint need one authoritative build path.
- `diagnose_failure` and `generate_candidate_fix` are not wired to real
  provider calls. The current candidate loop also needs to apply each patch
  before testing it; otherwise it can validate the unchanged baseline.
- Migrations `0014` and ORM models define `sandbox_runs`,
  `run_reviews`, and per-provider `model_candidate_fixes`. Runs are bound
  to the canonical repository and provider installation through a composite
  foreign key; a database trigger checks synthetic-injection consent.
  The orchestrator still uses an in-memory registry and does not write/read
  these tables; there is no tenant-scoped result API or end-to-end consent
  workflow.
- Container completion, malformed result handling, timeouts, cancellation,
  teardown and terminal-state persistence are not complete.

See `docs/known-gaps.md` and issue #94 for the implementation sequence and
acceptance gates.

## Authentication and deployment gate

Before exposing any Lab API, implement authenticated user identity and
installation-scoped tenant membership. Derive the reviewer ID from the
authenticated principal; never accept it as an authority-bearing request
field. Enforce membership/role checks on run creation, result reads, review,
and any later PR-creation endpoint. Keep the Lab service unmounted until
these checks and integration tests pass.

## Safety rule

Until the blockers above are closed and functional, adversarial, tenant
isolation, credential-scope, timeout, teardown, and end-to-end tests pass,
Lab execution must remain disabled for live repositories.
