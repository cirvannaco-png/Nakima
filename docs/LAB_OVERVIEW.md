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
- `repositories.provider_installation_id` associates a repository with its
  provider installation. Existing rows remain unattached until verified.
- Lab consent is stored on the canonical repository row. Legacy rows default
  to opted out. A database CHECK constraint prevents opt-in unless the
  installation, timestamp, actor, and consent-version are all present.

Migrations `0013` and `0014` add the provider tenant, consent, durable run,
candidate, and review schema. Every run stores both the canonical repository
ID and its provider-installation ID; a composite foreign key prevents a run
from being attributed to a different installation. Synthetic-injection runs
are additionally checked by a PostgreSQL trigger against the repository's
complete opt-in record. The old `db/schema.sql` UUID-based repository schema
was never part of the Alembic chain and is now explicitly marked deprecated
and non-executable. Do not apply it.

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

- `orchestrator/main.py` still accepts UUID repository/organization IDs,
  uses an in-memory run registry, and contains unimplemented consent,
  clone-resolution, result-polling, and persistence functions. Its request
  contract does not yet use the canonical integer repository key.
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

## Safety rule

Until the blockers above are closed and functional, adversarial, tenant
isolation, credential-scope, timeout, teardown, and end-to-end tests pass,
Lab execution must remain disabled for live repositories.
