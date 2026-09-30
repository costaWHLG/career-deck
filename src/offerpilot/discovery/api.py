"""发现层 REST：候选池摄取/查询、AI 评分、晋升投递、评分画像。

路由前缀 /api/discovery；写入语义见 ADR 0013。
评分是 AI 边界：无可用 provider 时返回 503，不降级为假分。
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.config import load_config
from offerpilot.discovery.contracts import (
    DiscoveryProfile,
    RawJobPayload,
    ReadonlyDraftCompleter,
)
from offerpilot.discovery.promote import CandidatePromotionService
from offerpilot.discovery.repository import CandidateNotFound, DiscoveryRepository
from offerpilot.discovery.scoring import CandidateScoringService
from offerpilot.discovery.sources.manual import ManualSourceAdapter
from offerpilot.repositories.application_jd_versions import (
    JDVersionError,
    JDVersionValidationError,
)


def _profile_from_dict(data: dict[str, Any]) -> DiscoveryProfile:
    def strings(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    return DiscoveryProfile(
        resume_text=str(data.get("resume_text", "") or ""),
        resume_id=data.get("resume_id"),
        cities=strings(data.get("cities")),
        directions=strings(data.get("directions")),
        salary_expectation=str(data.get("salary_expectation", "") or ""),
        red_lines=strings(data.get("red_lines")),
    )


def _repository_dict_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    return profile or {
        "resume_id": None,
        "resume_text": "",
        "cities": [],
        "directions": [],
        "salary_expectation": "",
        "red_lines": [],
    }


def register_discovery_routes(
    app: FastAPI,
    sessions: sessionmaker[Session],
    data_dir: Any,
    completer_factory: Callable[[], ReadonlyDraftCompleter] | None = None,
) -> None:
    repository = DiscoveryRepository(sessions)

    def build_completer() -> ReadonlyDraftCompleter:
        if completer_factory is not None:
            return completer_factory()
        from offerpilot.ai.client import ConfiguredAIClient

        return ConfiguredAIClient(load_config(data_dir))

    @app.get("/api/discovery/candidates")
    def list_candidates(status: str | None = None) -> JSONResponse:
        return JSONResponse(repository.list_candidates(status))

    @app.post("/api/discovery/candidates")
    def ingest_candidates(payload: dict[str, Any]) -> JSONResponse:
        """手动投喂入口：单条原始岗位或 {"jobs": [ ... ]} 批量。宽容摄取，原文入库。"""

        adapter = ManualSourceAdapter()
        try:
            payloads: list[RawJobPayload] = adapter.fetch(payload)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        rows = repository.ingest(payloads)
        return JSONResponse(rows, status_code=201)

    @app.get("/api/discovery/candidates/{candidate_id}")
    def get_candidate(candidate_id: int) -> JSONResponse:
        try:
            candidate = repository.get_candidate(candidate_id)
        except CandidateNotFound:
            return JSONResponse({"error": "候选不存在"}, status_code=404)
        return JSONResponse({**candidate, "scores": repository.list_scores(candidate_id)})

    @app.post("/api/discovery/candidates/{candidate_id}/score")
    def score_candidate(candidate_id: int) -> JSONResponse:
        try:
            candidate = repository.get_candidate(candidate_id)
        except CandidateNotFound:
            return JSONResponse({"error": "候选不存在"}, status_code=404)

        profile_data = _repository_dict_profile(repository.get_profile())
        profile = _profile_from_dict(profile_data)
        from offerpilot.discovery.contracts import NormalizedJob

        job = NormalizedJob(
            company_name=candidate.get("company_name", ""),
            position_name=candidate.get("position_name", ""),
            job_url=candidate.get("job_url", ""),
            city=candidate.get("city", ""),
            salary_text=candidate.get("salary_text", ""),
            experience_text=candidate.get("experience_text", ""),
            education_text=candidate.get("education_text", ""),
            jd_text=candidate.get("jd_text", ""),
            published_text=candidate.get("published_text", ""),
        )
        try:
            score = CandidateScoringService(build_completer()).score(job, profile)
        except ValueError as exc:
            return JSONResponse({"error": f"AI 评分暂不可用：{exc}"}, status_code=503)
        saved = repository.save_score(
            candidate_id, score, profile_fingerprint=profile_data.get("profile_fingerprint", "")
        )
        return JSONResponse(saved, status_code=201)

    @app.post("/api/discovery/candidates/{candidate_id}/promote")
    def promote_candidate(candidate_id: int, payload: dict[str, Any] | None = None) -> JSONResponse:
        body = payload or {}
        service = CandidatePromotionService(sessions)
        try:
            result = service.promote(
                candidate_id,
                status=str(body.get("status", "pending")),
                notes=str(body.get("notes", "")),
                key=body.get("key"),
            )
        except CandidateNotFound:
            return JSONResponse({"error": "候选不存在"}, status_code=404)
        except (JDVersionError, JDVersionValidationError, ValueError) as exc:
            status_code = getattr(exc, "status_code", 400)
            return JSONResponse({"error": str(exc)}, status_code=status_code)
        return JSONResponse(result, status_code=201)

    @app.patch("/api/discovery/candidates/{candidate_id}/status")
    def set_candidate_status(candidate_id: int, payload: dict[str, Any]) -> JSONResponse:
        status = str(payload.get("status", ""))
        try:
            return JSONResponse(repository.set_status(candidate_id, status))
        except CandidateNotFound:
            return JSONResponse({"error": "候选不存在"}, status_code=404)
        except ValueError:
            return JSONResponse({"error": "无效的候选状态"}, status_code=422)

    @app.get("/api/discovery/profile")
    def get_profile() -> JSONResponse:
        return JSONResponse(_repository_dict_profile(repository.get_profile()))

    @app.put("/api/discovery/profile")
    def put_profile(payload: dict[str, Any]) -> JSONResponse:
        profile = _profile_from_dict(payload)
        saved = repository.upsert_profile(profile)
        return JSONResponse(saved)
