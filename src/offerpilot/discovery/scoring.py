"""AI 评分边界（ADR 0013 §2.2）：七维加权评分 + 评级 + 红线判定。

输入 NormalizedJob + DiscoveryProfile，输出 CandidateScore；
AI 调用走只读草稿补全，不进 Agent 工具面。评分权重与评级口径是产品常量，不随模型变化。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from offerpilot.ai.types import Message
from offerpilot.discovery.contracts import (
    CandidateScore,
    DimensionScore,
    DiscoveryProfile,
    NormalizedJob,
    ReadonlyDraftCompleter,
)

# 七维权重（产品口径，ADR 0013）
DIMENSION_WEIGHTS: dict[str, float] = {
    "tech_match": 0.25,
    "salary": 0.20,
    "outlook": 0.15,
    "stability": 0.10,
    "growth": 0.10,
    "intensity": 0.10,
    "commute": 0.10,
}
DIMENSION_ORDER: tuple[str, ...] = tuple(DIMENSION_WEIGHTS)
NEUTRAL_SCORE = 3.0
SCORE_MIN = 1.0
SCORE_MAX = 5.0
GRADE_A_MIN = 4.0
GRADE_B_MIN = 3.0
INFORMATION_LACKING_MARKER = "信息不足"
# complete_readonly_draft 的硬约束：超时 ≤60 秒、消息 JSON ≤8192 字节（含系统提示）
SCORING_TIMEOUT_SECONDS = 60.0
PROFILE_TEXT_CAP = 1100
JD_TEXT_CAP = 1300

_SYSTEM_PROMPT = """你是资深求职顾问。对照候选人画像评估一个岗位，输出严格 JSON（无 Markdown 围栏）：
{
  "dimensions": {
    "tech_match": {"score": 1-5的数字, "reason": "一句话理由", "information_lacking": true/false},
    "salary": {...}, "outlook": {...}, "stability": {...},
    "growth": {...}, "intensity": {...}, "commute": {...}
  },
  "rationale": "两三句总结：值不值得投、最大风险",
  "red_line_hits": ["命中画像红线的项，无则空数组"]
}
要求：
1. 每维 score 为 1-5 的数字；信息不足的维度给 3 分且 information_lacking=true，reason 里带"信息不足"；
2. 与画像红线冲突的（如外包、薪资低于底线、方向排除）写入 red_line_hits；
3. 画像 cities/directions 与岗位明显不符时在 rationale 说明；
4. 只输出 JSON。"""


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return NEUTRAL_SCORE
    return max(SCORE_MIN, min(SCORE_MAX, score))


def _fingerprint(material: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class CandidateScoringService:
    """七维 AI 评分。completer 为只读补全实现（生产接 ConfiguredAIClient）。"""

    def __init__(self, completer: ReadonlyDraftCompleter) -> None:
        self.completer = completer

    def score(self, job: NormalizedJob, profile: DiscoveryProfile) -> CandidateScore:
        messages = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=self._build_user_payload(job, profile)),
        ]
        assistant = self.completer.complete_readonly_draft(
            messages, timeout_seconds=SCORING_TIMEOUT_SECONDS
        )
        parsed = self._parse_response(getattr(assistant, "content", "") or "")
        breakdown = self._build_breakdown(parsed.get("dimensions", {}))
        total = round(
            sum(dim.score * DIMENSION_WEIGHTS[dim.dimension] for dim in breakdown), 2
        )
        red_line_hits = tuple(
            str(hit) for hit in parsed.get("red_line_hits", []) if str(hit).strip()
        )
        grade = self._grade(total, red_line_hits)
        model_fingerprint = _fingerprint(
            {"prompt_version": "discovery-score-v1", "system": _SYSTEM_PROMPT}
        )
        return CandidateScore(
            breakdown=breakdown,
            total_score=total,
            grade=grade,
            rationale=str(parsed.get("rationale", "")).strip(),
            red_line_hits=red_line_hits,
            model_fingerprint=model_fingerprint,
        )

    @staticmethod
    def _build_user_payload(job: NormalizedJob, profile: DiscoveryProfile) -> str:
        profile_material = dict(profile.fingerprint_material())
        profile_material["resume_text"] = (
            (profile.resume_text or "")[:PROFILE_TEXT_CAP] + "…"
            if len(profile.resume_text or "") > PROFILE_TEXT_CAP
            else profile.resume_text
        )
        return json.dumps(
            {
                "candidate_profile": profile_material,
                "job": {
                    "company_name": job.company_name,
                    "position_name": job.position_name,
                    "city": job.city,
                    "salary_text": job.salary_text,
                    "experience_text": job.experience_text,
                    "education_text": job.education_text,
                    "jd_text": (
                        job.jd_text[:JD_TEXT_CAP] + "…"
                        if len(job.jd_text) > JD_TEXT_CAP
                        else job.jd_text
                    ),
                    "published_text": job.published_text,
                },
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        text = content.strip()
        fenced = re.search(r"\{.*\}", text, re.DOTALL)
        if fenced:
            text = fenced.group(0)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _build_breakdown(dimensions: dict[str, Any]) -> tuple[DimensionScore, ...]:
        breakdown: list[DimensionScore] = []
        for dimension in DIMENSION_ORDER:
            entry = dimensions.get(dimension) if isinstance(dimensions, dict) else None
            if not isinstance(entry, dict):
                entry = {}
            raw_score = entry.get("score", NEUTRAL_SCORE)
            score = _clamp_score(raw_score)
            reason = str(entry.get("reason", "")).strip()
            lacking = bool(entry.get("information_lacking", False)) or (
                INFORMATION_LACKING_MARKER in reason
            )
            if raw_score is None or not str(entry.get("score", "")).strip():
                lacking = True
            breakdown.append(
                DimensionScore(
                    dimension=dimension,
                    score=score,
                    reason=reason or (INFORMATION_LACKING_MARKER if lacking else ""),
                    is_information_lacking=lacking,
                )
            )
        return tuple(breakdown)

    @staticmethod
    def _grade(total: float, red_line_hits: tuple[str, ...]) -> str:
        if red_line_hits:
            return "C"
        if total >= GRADE_A_MIN:
            return "A"
        if total >= GRADE_B_MIN:
            return "B"
        return "C"
