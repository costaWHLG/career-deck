"""岗位发现层契约：多源接缝、规范记录、评分结构。

边界（见 ADR 0013）：
- 抓取行为只发生在 SourceAdapter 内部，其余层不接触外部数据；
- 归一化消化上游格式差异，评分层只面对 NormalizedJob；
- 评分是 AI 边界，输入含画像快照，输出可复算可追溯。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RawJobPayload:
    """多源原始岗位数据。raw 宽容保留，不做清洗。"""

    source: str
    source_key: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedJob:
    """规范岗位记录。字段缺失置空，未识别字段进 extra。"""

    company_name: str = ""
    position_name: str = ""
    job_url: str = ""
    city: str = ""
    salary_text: str = ""
    experience_text: str = ""
    education_text: str = ""
    jd_text: str = ""
    published_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryProfile:
    """评分输入画像：简历快照 + 地域/方向/薪资期望/红线。"""

    resume_text: str = ""
    resume_id: int | None = None
    cities: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    salary_expectation: str = ""
    red_lines: tuple[str, ...] = ()

    def fingerprint_material(self) -> dict[str, Any]:
        return {
            "resume_text": self.resume_text,
            "resume_id": self.resume_id,
            "cities": list(self.cities),
            "directions": list(self.directions),
            "salary_expectation": self.salary_expectation,
            "red_lines": list(self.red_lines),
        }


@dataclass(frozen=True)
class DimensionScore:
    """单维度评分。信息不足时 score 给中性 3 分并标注。"""

    dimension: str
    score: float
    reason: str
    is_information_lacking: bool = False


@dataclass(frozen=True)
class CandidateScore:
    """AI 评分结果：七维明细 + 总分 + 评级 + 理由 + 红线命中。"""

    breakdown: tuple[DimensionScore, ...]
    total_score: float
    grade: str
    rationale: str
    red_line_hits: tuple[str, ...] = ()
    model_fingerprint: str = ""


@runtime_checkable
class SourceAdapter(Protocol):
    """多源接入边界：抓取行为的唯一合法位置。"""

    name: str

    def fetch(self, query: dict[str, Any]) -> list[RawJobPayload]: ...


@runtime_checkable
class ReadonlyDraftCompleter(Protocol):
    """AI 评分边界：只读补全调用（生产接 ConfiguredAIClient）。"""

    def complete_readonly_draft(self, messages: list[Any], *, timeout_seconds: float) -> Any: ...
