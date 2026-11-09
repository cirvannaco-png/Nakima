# Known Gaps — Nakima Lab / Sandbox / Self-Healing v0.1

> **Release status:** not production-ready. The Lab is a scaffold, not an operational security boundary. See issue #94.

Explicit per Directive: undocumented gaps are liabilities. This is what's
real vs. stubbed right now.

## Database identity and tenant foundation

- Migration `0013` adds a provider-neutral `provider_installations` table and links the existing integer-keyed `repositories` rows to an internal installation ID. External provider IDs are stored as strings and uniquely scoped by provider.
- Legacy repositories remain unattached and Lab-opted-out. A database CHECK constraint requires an installation, consent timestamp, actor identifier, and consent version before opt-in.
- Migration `0014` defines `sandbox_runs`, `run_reviews`, and
  `model_candidate_fixes`. Every run carries the canonical repository ID and
  provider-installation ID under a composite FK; PostgreSQL enforces synthetic
  injection consent with a trigger. The tables are not yet wired into the
  orchestrator, and verified webhook metadata is not yet upserted into
  provider-installation rows.
- `db/schema.sql` was a separate UUID-based draft, not an Alembic migration and not part of ORM metadata. It is now marked deprecated/non-executable; do not apply it. The integer `repositories.id` remains canonical.

## API exposure and authorization blocker

- The Lab FastAPI app in `orchestrator/main.py` is not mounted by the main
  `api.router:app` and is not run by the current Compose services. The
  production Dockerfile starts only `api.router:app`; the Compose
  `sandbox` service only builds the runner image.
- Keep the Lab app unexposed. It has no authenticated principal/tenant
  membership dependency, takes UUID repository/organization identifiers
  from the request, and accepts `reviewer_user_id` from the caller. A client
  must never choose the reviewer identity or authorize its own tenant access.
- Before mounting/deploying Lab endpoints, implement authentication,
  installation-scoped membership/role checks, server-derived reviewer
  identity, and authorization on run, read, review, and eventual PR-creation
  operations.

## Stubbed, needs implementation before first live test

- `orchestrator/main.py::_repo_has_lab_consent` — still a placeholder; must
  query the canonical repository row and fail closed unless the consent record
  is complete, the provider installation is active, and the caller is
  authorized for that installation.
- `orchestrator/main.py::_resolve_clone_url` — must resolve a verified
  provider installation and issue a **read-only**, single-repository token.
  Never pass the workflow token or an org-wide PAT to the sandbox.
- `orchestrator/main.py::_await_container_completion` — needs real container
  log polling + a defined structured JSON contract the sandbox entrypoint
  writes before exit. The database now has a `result_schema_version` field,
  but the Pydantic result contract and persistence path are still missing.
- `orchestrator/self_healing.py::diagnose_failure` and
  `generate_candidate_fix` — need real model API wiring. Structured output
  schemas need to be nailed down and tested against real CI logs from Nakima
  and Medis-Touch before trusting them on other repos.

## Deliberately simplified, revisit only with evidence

- `_rough_diff_agreement` uses string-set uniqueness as a placeholder for
  cross-model agreement. Should become AST-normalized diff comparison, but
  not worth building until you have real multi-model candidate data to
  validate the smarter version against.
- Tie-break in `run_self_healing_loop` (`max(passing, key=lambda c:
  len(c.rationale...))`) is a placeholder, not a real selection heuristic.
  Needs a real judge step (likely: one more model call asking "which of
  these N passing candidates is the cleanest fix, and why") before this
  is trustworthy on ambiguous cases.
- `MAX_CONCURRENT_RUNS = 4` and `MAX_HEAL_ATTEMPTS = 3` are reasonable
  starting ceilings, not measured values. Revisit once you have real
  first-test data on run duration and failure/retry rates.

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

- Replace in-container cloning: the current entrypoint needs network access
  while the orchestrator disables container networking. Clone on the trusted
  host at the pinned commit, then transfer a verified immutable archive.
- Confirm sandbox container truly has `network_mode="none"` end-to-end (no
  sidecar, no DNS resolution path that leaks out).
- Confirm the GitHub App installation token scoping is actually read-only at
  the GitHub API level, not just "we don't call write endpoints" — a
  write-scoped token that's merely unused in code is still a live risk if
  the sandbox is ever compromised.
- Confirm `synthetic_injection_used` DB trigger (schema.sql) is tested with
  an actual attempted bypass, not just reviewed by eye.
