"""发现层数据模型：候选池、评分结果、评分画像（ADR 0013）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from offerpilot.models import Base


class JobCandidate(Base):
    __tablename__ = "job_candidates"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_job_candidates_source_key"),
        Index("idx_job_candidates_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_payload_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")
    company_name: Mapped[str] = mapped_column(String, default="", server_default="")
    position_name: Mapped[str] = mapped_column(String, default="", server_default="")
    job_url: Mapped[str] = mapped_column(String, default="", server_default="")
    city: Mapped[str] = mapped_column(String, default="", server_default="")
    salary_text: Mapped[str] = mapped_column(String, default="", server_default="")
    experience_text: Mapped[str] = mapped_column(String, default="", server_default="")
    education_text: Mapped[str] = mapped_column(String, default="", server_default="")
    jd_text: Mapped[str] = mapped_column(String, default="", server_default="")
    published_text: Mapped[str] = mapped_column(String, default="", server_default="")
    extra_json: Mapped[str] = mapped_column(String, default="{}", server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    promoted_application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class JobCandidateScore(Base):
    __tablename__ = "job_candidate_scores"
    __table_args__ = (
        Index("idx_job_candidate_scores_candidate", "candidate_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("job_candidates.id", ondelete="CASCADE"), nullable=False
    )
    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_fingerprint: Mapped[str] = mapped_column(String(64), default="", server_default="")
    breakdown_json: Mapped[str] = mapped_column(String, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    rationale: Mapped[str] = mapped_column(String, default="", server_default="")
    red_line_hits_json: Mapped[str] = mapped_column(String, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class DiscoveryProfile(Base):
    """评分画像单例行：简历关联 + 地域/方向/薪资期望/红线。"""

    __tablename__ = "discovery_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    resume_text: Mapped[str] = mapped_column(String, default="", server_default="")
    cities_json: Mapped[str] = mapped_column(String, default="[]", server_default="[]")
    directions_json: Mapped[str] = mapped_column(String, default="[]", server_default="[]")
    salary_expectation: Mapped[str] = mapped_column(String, default="", server_default="")
    red_lines_json: Mapped[str] = mapped_column(String, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
