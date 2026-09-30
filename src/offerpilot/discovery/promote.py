"""晋升边界：候选 -> Application 走既有单一 intake（ADR 0013 §2.3）。

幂等：已晋升候选重复晋升返回既有 application_id；
创建请求带稳定 idempotency_key，进程重启后复放仍得到同一 Application。
"""
from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from offerpilot.discovery.repository import DiscoveryRepository
from offerpilot.repositories.application_creation import ApplicationCreationService
from offerpilot.repositories.applications import ApplicationCreate

PROMOTE_IDEMPOTENCY_PREFIX = "discovery-promote"
PROMOTE_STATUS = "pending"  # 词汇表"待投递"：晋升=决定投递，进入投递管理
PROMOTE_SOURCE = "discovery"


class CandidatePromotionService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.candidates = DiscoveryRepository(sessions)

    def promote(
        self,
        candidate_id: int,
        *,
        status: str = PROMOTE_STATUS,
        notes: str = "",
        key: str | None = None,
    ) -> dict[str, object]:
        candidate = self.candidates.get_candidate(candidate_id)
        existing_application_id = candidate.get("promoted_application_id")
        if existing_application_id:
            return {
                "candidate_id": candidate_id,
                "application_id": existing_application_id,
                "replayed": True,
            }

        # 确定性幂等键：崩溃复放（create 成功但链接未写）仍落到同一 Application
        creation_key = key or f"{PROMOTE_IDEMPOTENCY_PREFIX}-{candidate_id}"
        data = ApplicationCreate(
            company_name=candidate["company_name"],
            position_name=candidate["position_name"],
            job_url=candidate.get("job_url", "") or "",
            status=status,
            source=PROMOTE_SOURCE,
            notes=notes,
        )
        initial_jd = None
        if candidate.get("jd_text"):
            initial_jd = {"jd_text": candidate["jd_text"], "source_url": candidate.get("job_url", "")}

        result, replayed = ApplicationCreationService(self.sessions).create(
            data, initial_jd=initial_jd, key=creation_key
        )
        application_id = int(result["id"])
        self.candidates.link_promotion(candidate_id, application_id)
        return {
            "candidate_id": candidate_id,
            "application_id": application_id,
            "replayed": replayed,
        }
