"""The PDF Report Generator from the EIP spec. Reads exclusively from data
that already exists — ProjectRealityModel (Project DNA), UserIntent,
EvolutionRoadmap (Recommendations), EngineeringDecision/EngineeringEvent
(Decision Registry + Event Log) — and renders it. Generates nothing new
and makes no judgment calls of its own; any judgment in the report (e.g.
an Intent Confidence Score) is computed by re-using neis/reasoning's
EvidenceEngine rather than reimplementing the same logic here.
"""
