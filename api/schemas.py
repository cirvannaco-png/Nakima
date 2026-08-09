from typing import Any, Literal

from pydantic import BaseModel, Field


class RepositoryIndexRequest(BaseModel):
    repo_full_name: str
    github_token: str


class RepositoryIndexResponse(BaseModel):
    repository_id: int
    nodes_created: int
    edges_created: int


class HealthScoreResponse(BaseModel):
    score: float | None
    components: dict[str, Any] | None = None
    reason: str | None = None


class SymbolLookupResponse(BaseModel):
    id: str
    name: str
    node_type: str
    file_path: str | None
    line_start: int | None
    line_end: int | None


class PolicyUpdateRequest(BaseModel):
    branch_pattern: str | None = None
    required_reviewers: list[str] | None = None
    require_docstrings: bool | None = None
    require_license: bool | None = None
    review_required: bool | None = None


class DecisionCreateRequest(BaseModel):
    context: str
    problem: str
    decision: str
    justification: str
    alternatives: list[dict[str, Any]] = []
    consequences: str | None = None
    related_files: list[str] = []
    related_issues: list[str] = []
    author: str = "user"


class DecisionResponse(BaseModel):
    id: str
    repository_id: int
    context: str
    problem: str
    decision: str
    justification: str
    alternatives: list[dict[str, Any]]
    consequences: str | None
    related_files: list[str]
    related_issues: list[str]
    author: str
    created_at: str


class EventResponse(BaseModel):
    id: str
    repository_id: int
    task_id: str | None
    decision_id: str | None
    timestamp: str
    author: str
    task_description: str
    files_modified: list[str]
    reason: str
    chosen_solution: str
    risk_level: str
    verification_status: str
    tests_executed: list[str]


class ReportResponse(BaseModel):
    id: str
    repository_id: int
    version: int
    executive_summary: str
    sections_included: list[str]
    generated_at: str


class SecurityScanRequest(BaseModel):
    github_token: str | None = None
    target_url: str | None = None
    run_pentest_simulator: bool = False


class SecurityFindingResponse(BaseModel):
    id: str
    source: str
    rule: str
    severity: str
    file_path: str
    line_number: int | None
    detail: str
    status: str
    first_seen_at: str
    last_seen_at: str


class SecurityScanResponse(BaseModel):
    score: float
    counts_by_severity: dict[str, int]
    total_open: int
    new_finding_count: int
    resolved_finding_count: int
    scanners_run: list[str]
    scanners_skipped: list[str]


class DocumentResponse(BaseModel):
    id: str
    repository_id: int
    filename: str
    file_type: str
    size_bytes: int
    size_kb: float  # size_bytes / 1024, rounded to 1 dp — convenience for UI
    version: int
    status: str
    rejection_reason: str | None
    extracted_text_preview: str | None
    is_duplicate: bool = False
    sha256: str | None  # first 64 hex chars of content_hash (sha256 of file bytes)
    virus_status: str  # "clean" | "infected" | "unavailable" | "error"
    uploaded_at: str


class NEISAnalyzeRequest(BaseModel):
    github_token: str


class NEISAnalyzeResponse(BaseModel):
    roadmap_id: str
    reality_id: str
    recommendation_count: int
    stages_completed: list[str]
    stages_failed: dict[str, str]


class NEISRoadmapItemResponse(BaseModel):
    id: str
    category: str
    title: str
    rationale: str
    priority_score: float
    effort_estimate: str
    status: str


class NEISRoadmapResponse(BaseModel):
    id: str
    status: str
    summary: str
    generated_at: str
    items: list[NEISRoadmapItemResponse]


class NEISRealityResponse(BaseModel):
    id: str
    languages: dict[str, int]
    dependencies: list[dict[str, Any]]
    loc_by_language: dict[str, int]
    file_count: int
    test_file_count: int
    health_score: float | None
    created_at: str


class NEISIntentRequest(BaseModel):
    goals: list[str] = []
    constraints: list[str] = []
    priority_weights: dict[str, float] = {}
    notes: str | None = None


class NEISIntentResponse(BaseModel):
    id: str
    goals: list[str]
    constraints: list[str]
    priority_weights: dict[str, float]
    notes: str | None


class NEISRoadmapItemStatusRequest(BaseModel):
    # Deliberately excludes PROPOSED (the only initial state, never a valid
    # target) and COMPLETED (set by the pipeline once work lands, not by a
    # reviewer clicking accept/dismiss).
    status: Literal["accepted", "dismissed"]
    # Same auth posture as NEISAnalyzeRequest.github_token: a caller-supplied
    # PAT, not the GitHub App's installation-token flow, because Repository
    # doesn't store an installation_id to look one up from. Optional —
    # dismissing needs no GitHub write, and accepting without a token just
    # records the decision without opening an issue.
    github_token: str | None = None


class NEISRoadmapItemStatusResponse(BaseModel):
    id: str
    status: str
    issue_url: str | None = None


# --- Market Research (market_research/) -------------------------------------


class MarketResearchScanRequest(BaseModel):
    # Caller-supplied research topics, not inferred from the repo — see
    # research_scout.py's docstring for why. At least one required.
    queries: list[str] = Field(min_length=1, max_length=10)
    # Free-text description of the product/repo, given to the Judge and
    # Opportunity Engine as context for relevance judgments — e.g. "Cirvanna,
    # an AI fashion identity platform for the African luxury market."
    repo_context: str = Field(min_length=1, max_length=2000)


class MarketResearchScanResponse(BaseModel):
    signals_collected: int
    signals_judged: int
    signals_accepted: int
    opportunities_generated: int
    stages_completed: list[str]
    stages_failed: dict[str, str]


class ExternalSignalResponse(BaseModel):
    id: str
    query: str
    title: str
    url: str
    snippet: str
    judge_verdict: str
    judge_rationale: str | None


class ExternalOpportunityResponse(BaseModel):
    id: str
    title: str
    description: str
    confidence: float
    status: str
    source_signal_ids: list[str]
    created_at: str


class OpportunityPromoteResponse(BaseModel):
    opportunity_id: str
    roadmap_item_id: str
    roadmap_item_status: str
