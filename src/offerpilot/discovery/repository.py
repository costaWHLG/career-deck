"""候选池仓储：摄取去重、列表查询、评分落库、画像读写、晋升链接。

不抓取外部数据、不调模型（与 application_creation.py 同一红线）。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.discovery.contracts import (
    CandidateScore,
    DiscoveryProfile,
    NormalizedJob,
    RawJobPayload,
)
from offerpilot.discovery.models import DiscoveryProfile as DiscoveryProfileRow
from offerpilot.discovery.models import JobCandidate, JobCandidateScore
from offerpilot.discovery.normalize import (
    candidate_source_key,
    normalize_raw_job,
    raw_payload_to_json,
)

CANDIDATE_STATUSES = ("new", "scored", "promoted", "discarded")


class CandidateNotFound(ValueError):
    pass


def _job_to_columns(job: NormalizedJob) -> dict[str, Any]:
    return {
        "company_name": job.company_name,
        "position_name": job.position_name,
        "job_url": job.job_url,
        "city": job.city,
        "salary_text": job.salary_text,
        "experience_text": job.experience_text,
        "education_text": job.education_text,
        "jd_text": job.jd_text,
        "published_text": job.published_text,
        "extra_json": json.dumps(job.extra, ensure_ascii=False, sort_keys=True),
    }


class DiscoveryRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    # ---- 摄取 ----

    def ingest(self, payloads: list[RawJobPayload]) -> list[dict[str, Any]]:
        """归一化并按 (source, source_key) 幂等入库；重复投喂刷新数据不建新行。"""

        rows: list[dict[str, Any]] = []
        with self.sessions() as session:
            for payload in payloads:
                source_key = candidate_source_key(payload)
                existing = session.scalar(
                    select(JobCandidate).where(
                        JobCandidate.source == payload.source,
                        JobCandidate.source_key == source_key,
                    )
                )
                job = normalize_raw_job(payload)
                columns = _job_to_columns(job)
                if existing is not None:
                    for name, value in columns.items():
                        setattr(existing, name, value)
                    existing.raw_payload_json = raw_payload_to_json(payload)
                    rows.append(self._row_to_dict(existing))
                    continue
                candidate = JobCandidate(
                    source=payload.source,
                    source_key=source_key,
                    raw_payload_json=raw_payload_to_json(payload),
                    status="new",
                    **columns,
                )
                session.add(candidate)
                session.flush()
                rows.append(self._row_to_dict(candidate))
            session.commit()
        return rows

    # ---- 查询 ----

    def list_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            statement = select(JobCandidate).order_by(JobCandidate.discovered_at.desc())
            if status:
                statement = statement.where(JobCandidate.status == status)
            return [self._row_to_dict(row) for row in session.scalars(statement)]

    def get_candidate(self, candidate_id: int) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(JobCandidate, candidate_id)
            if row is None:
                raise CandidateNotFound(f"候选不存在: {candidate_id}")
            return self._row_to_dict(row)

    def list_scores(self, candidate_id: int) -> list[dict[str, Any]]:
        with self.sessions() as session:
            statement = (
                select(JobCandidateScore)
                .where(JobCandidateScore.candidate_id == candidate_id)
                .order_by(JobCandidateScore.created_at.desc())
            )
            return [self._score_to_dict(row) for row in session.scalars(statement)]

    # ---- 评分落库 ----

    def save_score(
        self,
        candidate_id: int,
        score: CandidateScore,
        profile_fingerprint: str,
    ) -> dict[str, Any]:
        with self.sessions() as session:
            candidate = session.get(JobCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFound(f"候选不存在: {candidate_id}")
            row = JobCandidateScore(
                candidate_id=candidate_id,
                profile_fingerprint=profile_fingerprint,
                model_fingerprint=score.model_fingerprint,
                breakdown_json=json.dumps(
                    [asdict(dim) for dim in score.breakdown], ensure_ascii=False
                ),
                total_score=score.total_score,
                grade=score.grade,
                rationale=score.rationale,
                red_line_hits_json=json.dumps(
                    list(score.red_line_hits), ensure_ascii=False
                ),
            )
            session.add(row)
            if candidate.status in ("new", "scored"):
                candidate.status = "scored"
            session.flush()
            result = self._score_to_dict(row)
            session.commit()
            return result

    def link_promotion(self, candidate_id: int, application_id: int) -> dict[str, Any]:
        with self.sessions() as session:
            candidate = session.get(JobCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFound(f"候选不存在: {candidate_id}")
            candidate.promoted_application_id = application_id
            candidate.status = "promoted"
            session.commit()
            return self._row_to_dict(candidate)

    def set_status(self, candidate_id: int, status: str) -> dict[str, Any]:
        if status not in CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate status: {status}")
        with self.sessions() as session:
            candidate = session.get(JobCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFound(f"候选不存在: {candidate_id}")
            candidate.status = status
            session.commit()
            return self._row_to_dict(candidate)

    # ---- 画像 ----

    def get_profile(self) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalars(select(DiscoveryProfileRow)).first()
            return None if row is None else self._profile_to_dict(row)

    def upsert_profile(self, profile: DiscoveryProfile) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.scalars(select(DiscoveryProfileRow)).first()
            if row is None:
                row = DiscoveryProfileRow()
                session.add(row)
            row.resume_id = profile.resume_id
            row.resume_text = profile.resume_text
            row.cities_json = json.dumps(list(profile.cities), ensure_ascii=False)
            row.directions_json = json.dumps(list(profile.directions), ensure_ascii=False)
            row.salary_expectation = profile.salary_expectation
            row.red_lines_json = json.dumps(list(profile.red_lines), ensure_ascii=False)
            session.commit()
            return self._profile_to_dict(row)

    # ---- 映射 ----

    @staticmethod
    def _row_to_dict(row: JobCandidate) -> dict[str, Any]:
        return {
            "id": row.id,
            "source": row.source,
            "source_key": row.source_key,
            "company_name": row.company_name,
            "position_name": row.position_name,
            "job_url": row.job_url,
            "city": row.city,
            "salary_text": row.salary_text,
            "experience_text": row.experience_text,
            "education_text": row.education_text,
            "jd_text": row.jd_text,
            "published_text": row.published_text,
            "extra": json.loads(row.extra_json or "{}"),
            "status": row.status,
            "promoted_application_id": row.promoted_application_id,
            "discovered_at": row.discovered_at.isoformat() if row.discovered_at else None,
        }

    @staticmethod
    def _score_to_dict(row: JobCandidateScore) -> dict[str, Any]:
        return {
            "id": row.id,
            "candidate_id": row.candidate_id,
            "profile_fingerprint": row.profile_fingerprint,
            "model_fingerprint": row.model_fingerprint,
            "breakdown": json.loads(row.breakdown_json or "[]"),
            "total_score": row.total_score,
            "grade": row.grade,
            "rationale": row.rationale,
            "red_line_hits": json.loads(row.red_line_hits_json or "[]"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _profile_to_dict(row: DiscoveryProfileRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "resume_id": row.resume_id,
            "resume_text": row.resume_text,
            "cities": json.loads(row.cities_json or "[]"),
            "directions": json.loads(row.directions_json or "[]"),
            "salary_expectation": row.salary_expectation,
            "red_lines": json.loads(row.red_lines_json or "[]"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
