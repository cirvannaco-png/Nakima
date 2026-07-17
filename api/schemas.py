from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RepositoryIndexRequest(BaseModel):
    repo_full_name: str
    github_token: str


class RepositoryIndexResponse(BaseModel):
    repository_id: int
    nodes_created: int
    edges_created: int


class HealthScoreResponse(BaseModel):
    score: Optional[float]
    components: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class SymbolLookupResponse(BaseModel):
    id: str
    name: str
    node_type: str
    file_path: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]


class PolicyUpdateRequest(BaseModel):
    branch_pattern: Optional[str] = None
    required_reviewers: Optional[List[str]] = None
    require_docstrings: Optional[bool] = None
    require_license: Optional[bool] = None
    review_required: Optional[bool] = None
