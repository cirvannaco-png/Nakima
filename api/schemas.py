from typing import Any

from pydantic import BaseModel


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
