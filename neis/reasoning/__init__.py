"""NEIS's internal reasoning pipeline: Evidence -> Cognitive -> Arbitration
-> Decision. This is the concrete shape of "NEIS as reasoning core" —
deterministic evidence and LLM-assisted judgment are kept as separate,
differently-trusted inputs that get reconciled explicitly, rather than
merged under one undifferentiated "reasoning" call.

- `evidence_engine.EvidenceEngine` — deterministic, rule-based, same
  design philosophy as `neis/analyzers/innovation_engine.py`'s
  `InnovationReasoningEngine` (which remains the Evidence Engine for
  *recommendation generation* specifically and is untouched by this
  module). This module's `EvidenceEngine` covers the two deterministic
  checks the Decision Engine needs: Intent Confidence scoring and
  hard-constraint violation detection. Same output for the same input,
  always. No network calls, no LLM.

- `cognitive_engine.CognitiveEngine` — LLM-assisted judgment for
  questions with no single correct answer (e.g. "does this plan align
  with the stated goals?"). Never authoritative on its own. Falls back to
  a neutral, zero-confidence assessment when no provider is configured or
  the call fails, same fallback discipline as
  `InnovationReasoningEngine.summarize()`.

- `arbitration_engine.ArbitrationEngine` — reconciles the two. A hard
  constraint violation from EvidenceEngine always wins regardless of what
  CognitiveEngine says. Absent a hard violation, CognitiveEngine's
  judgment is weighted by its own reported confidence and by whether
  intent is well-specified enough to judge against at all (Intent
  Confidence Score). Produces one of: approve / warn / request_confirmation
  / block, each with an explicit, human-readable reasoning trail — this
  trail is what gets written into the Engineering Decision Registry
  (`intelligence/decision_registry.py`), so every arbitration outcome is
  independently auditable later, not just logged as a bare verdict.

- `decision_engine.DecisionEngine` — the only class outside this package
  that callers (currently `orchestrator/workflow.py`) need to import.
  Loads the latest ProjectRealityModel and active UserIntent, runs all
  three engines, returns a `DriftValidationResult`. This is the Intent
  Drift Validator from the EIP spec.

What this deliberately does NOT do yet: become the top-level orchestrator.
`orchestrator/workflow.py` still owns the pipeline and calls into
`DecisionEngine` as one step among several (see the call site right after
planning, before code generation) — this is Phase 2 of the migration path
(workflow delegates increasing responsibility to NEIS) rather than Phase 3
(control flow inversion), which is future work, not this change.
"""
