"""Engineering Intelligence Engine (EIE) persistence models.

This is deliberately a separate module from `models/neis/`, not a rename
or a merge, because the two systems answer different questions:

- NEIS (`models/neis/`) is proactive: "given what this repo currently is,
  what should change?" It produces a superseding roadmap of recommendations
  nobody has necessarily acted on yet.
- EIE (this module) is a retrospective ledger: "what did Nakima (or a
  human) actually decide and do, and why?" It records real actions taken
  by the reactive issue-to-PR pipeline (`orchestrator/workflow.py`) and
  any manually-logged architectural decisions. Rows here are never
  superseded — they're an append-only audit trail, closer in spirit to
  `models/neis/project_reality.py`'s snapshot append-only-ness than to
  `EvolutionRoadmap`'s active/superseded lifecycle.

Two tables, not one, for the same reason `models/task.py` and
`models/knowledge.py` stay separate: `EngineeringDecision` is a deliberate,
often-manual record of *why* an architectural or design choice was made
(context/alternatives/justification/consequences) — it can exist with no
code change at all. `EngineeringEvent` is an automatic record of *what
Nakima did* for a specific task (files touched, tests run, verification
outcome) — it's written by the orchestrator, not a human. A decision can
reference zero, one, or many events; an event can reference zero or one
decision. Collapsing them into one table would force every quick "just
fixed a typo" event to carry decision-record fields it doesn't have, or
force every architectural decision to pretend it has file-level event
data it doesn't have yet.
"""
