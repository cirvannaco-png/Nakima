# Known Gaps — Nakima Lab / Sandbox / Self-Healing v0.1

Explicit per Directive: undocumented gaps are liabilities. This is what's
real vs. stubbed right now.

## Stubbed, needs implementation before first live test

- `orchestrator/main.py::_repo_has_lab_consent` — reads a placeholder; must
  wire to `repositories.sandbox_lab_opt_in`.
- `orchestrator/main.py::_resolve_clone_url` — must issue a **read-only**,
  repo-scoped GitHub App installation token. Never the org PAT. Never write scope.
- `orchestrator/main.py::_await_container_completion` — needs real container
  log polling + a defined structured JSON contract the sandbox entrypoint
  writes before exit (schema TBD, should live in `sandbox_image/`).
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

- Confirm sandbox container truly has `network_mode="none"` end-to-end (no
  sidecar, no DNS resolution path that leaks out).
- Confirm the GitHub App installation token scoping is actually read-only at
  the GitHub API level, not just "we don't call write endpoints" — a
  write-scoped token that's merely unused in code is still a live risk if
  the sandbox is ever compromised.
- Confirm `synthetic_injection_used` DB trigger (schema.sql) is tested with
  an actual attempted bypass, not just reviewed by eye.
