# NEIS Learning Policy

## The one rule that matters

**Nothing updates NEIS's shared base model live, in-run, from a sandbox result.**

Every self-healing run produces outcome data. That data becomes a candidate
row in `pattern_memory` with `promoted_to_base_model = false`. It stays
`false` until a separate, deliberate, offline batch process reviews it and
flips it — manually, by you, on a cadence you control (weekly to start).

This directly replaces the earlier "live update during runs" design. Reasons,
concretely:

- **Cross-tenant contamination.** A live-updating shared model means Repo A's
  outcome can shift behavior for Repo B before anyone has reviewed whether
  Repo A's outcome was even correct. One bad fix in production becomes a bad
  prior for every other user within minutes.
- **No audit trail for "why did it do that."** If weights update per-run, you
  cannot answer a user's "why did Nakima suggest X" without replaying live
  training history. If promotion is batch and versioned, you can point to
  exactly which pattern-memory snapshot produced which model version.
- **Small-sample overfitting.** Your first live tests will be a handful of
  runs. Any online-learning system will overfit to whatever those first runs
  happen to look like. Batch review with human judgment is the correction
  mechanism a live loop doesn't have.

## The pipeline

```
sandbox_runs (per-repo, isolated)
        │  outcome logged: fix_correct / fix_incorrect / no_fix_found
        ▼
pattern_memory candidate row
   (abstracted: vulnerability_class, fix_pattern, context_features — never raw diff)
   promoted_to_base_model = false
        │
        │  weekly batch review (human, initially you)
        ▼
   accept -> promoted_to_base_model = true, promoted_at = now(), version tag
   reject -> stays false, kept for the record (negative examples matter too)
        │
        ▼
   NEIS base model retrain job (offline, versioned, reviewable diff of behavior)
        │
        ▼
   New NEIS version deployed to all sandboxes
```

## What counts as "abstracted enough" for pattern_memory

Enforced structurally in `db/schema.sql` (see `no_raw_diff_markers` and
`reasonable_summary_length` constraints), but the intent in plain language:

- OK: `"SQL injection via string-formatted query in an ORM-adjacent codebase; fix pattern: parameterized query substitution"`
- NOT OK: the literal diff, the literal file path, the literal variable/table names from a real user's repo

If a pattern can't be described abstractly without losing its value, it's not
ready for the shared base — it stays a per-repo-isolated learning, full stop.

## Third-party model outputs (Claude, Gemini, Kimi, DeepSeek, GPT)

`model_candidate_fixes.retained_for_training` defaults to `false` and must
stay `false` for any provider until that provider's ToS has been reviewed and
cleared. Runtime candidate selection (asking multiple models for a fix and
picking the best one to show the user) is unambiguously fine. Persisting
those outputs as training data for NEIS is a separate legal question per
provider — treat it as blocked until reviewed, not as blocked-by-default-but-
easy-to-flip. See `docs/PROVIDER_TOS_NOTES.md`.

## Known gap

The batch promotion review is currently manual (you, reviewing a weekly
queue). That's correct for the current run volume — do not build tooling to
automate promotion decisions until you have enough reviewed history to know
what a bad promotion looks like. Automating this too early just moves the
overfitting risk from "live" to "weekly batch" instead of removing it.
