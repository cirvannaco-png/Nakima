from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class RepositoryPolicy(Base):
    __tablename__ = "repository_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), unique=True)
    branch_pattern: Mapped[str | None] = mapped_column(String(100), nullable=True)
    required_checks: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Added — PolicyChecker.check_required_reviewers referenced
    # policy.required_reviewers in the original draft, but no such column
    # existed on this model at all.
    required_reviewers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    require_docstrings: Mapped[bool] = mapped_column(Boolean, default=False)
    require_license: Mapped[bool] = mapped_column(Boolean, default=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    additional_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
