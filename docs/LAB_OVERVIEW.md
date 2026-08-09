# Nakima Lab & Sandbox — Overview

What this is: the environment where Nakima tests fixes, scans for CVEs, and
(opt-in only) stress-tests repos with synthetic vulnerabilities — all before
a human ever sees a proposed change on their real repo.

## How the pieces fit

```
User repo (connected, live) ─────────────────────────┐
                                                       │ read-only clone,
                                                       │ pinned to one commit
                                                       ▼
                              ┌─────────────────────────────────────────┐
                              │   Ephemeral container (network: none)    │
                              │   sandbox_image/entrypoint.py            │
                              │                                          │
                              │   1. clone at commit_sha                 │
                              │   2. baseline full-suite run (control)   │
                              │   3. CVE scan / synthetic inject (opt-in)│
                              │   4. self_healing.run_self_healing_loop  │
                              │      - diagnose                         │
                              │      - N candidates across providers    │
                              │      - validate each vs FULL suite       │
                              │      - compute confidence, not assert it │
                              │      - bounded to MAX_HEAL_ATTEMPTS       │
                              │   5. write ONE result.json, exit         │
                              └───────────────────┬──────────────────────┘
                                                   │ orchestrator/main.py
                                                   │ collects result, destroys
                                                   │ container (always, even
                                                   │ on failure/timeout)
                                                   ▼
                                    sandbox_runs row (tenant-isolated,
                                    db/schema.sql)
                                                   │
                                                   ▼
                                    Dashboard: user reviews diagnosis + diff
                                                   │
                                          ┌────────┴────────┐
                                          ▼                 ▼
                                     approve            reject
                                          │
                                          ▼
                              User explicitly triggers PR creation
                              (separate action from approval — two
                               deliberate steps, not one)
                                          │
                                          ▼
                                    PR opened on real repo
                                    (Nakima never auto-merges)

  ── separately, offline, weekly ──
  sandbox_runs outcomes → pattern_memory candidates (abstracted only)
        → human batch review → promoted_to_base_model flips
        → NEIS base model retrain (versioned, not live)
        → new NEIS version ships to all future sandbox runs
```

## What's real vs. what's a stub right now

See `docs/known-gaps.md` for the full list. Short version: the architecture,
isolation guarantees, DB-level consent enforcement, and the self-healing
loop's control flow (bounded retry, full-suite validation, computed
confidence) are real and specific. The actual model API calls
(`diagnose_failure`, `generate_candidate_fix`) and the CVE database are
interfaces waiting on your provider keys and a pre-baked vulnerability feed
— that's the next work, not this pass.

## Three isolation guarantees worth re-stating plainly

1. **Network**: sandbox containers run with `network_mode="none"`. They
   cannot reach production infra, cannot reach the live internet, cannot
   exfiltrate anything even if something inside the loop misbehaves.
2. **Tenancy**: `sandbox_runs` and everything in it is scoped to one
   `repository_id`/`organization_id` and never read cross-tenant.
   `pattern_memory` is the only bridge to the shared NEIS base, and it's
   structurally (DB CHECK constraints) forbidden from holding raw code.
3. **Human gate**: nothing reaches the real repo without an explicit
   approval, and PR creation is a second explicit action after approval —
   not an automatic consequence of a high confidence score.

## Immediate next step

Wire `diagnose_failure` in `self_healing.py` against Claude using a real
Nakima or Medis-Touch CI failure log as the first test input — that gives
you one fully working path end-to-end before adding Gemini/GPT/DeepSeek/Kimi
as additional candidate generators.
