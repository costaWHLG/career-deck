"""多源宽容归一化：RawJobPayload.raw -> NormalizedJob。

设计口径（ADR 0013 §2.1）：上游字段命名/结构差异全部消化在本层；
已识别字段进规范列，未识别字段原样落入 extra；任何字段缺失置空不报错。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from offerpilot.discovery.contracts import NormalizedJob, RawJobPayload

# 规范字段 -> 常见同义键（按优先级）。字符串比较大小写不敏感。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "company_name": (
        "company_name", "company", "corpname", "brandname", "companyname",
        "公司", "公司名称", "企业名称",
    ),
    "position_name": (
        "position_name", "job_name", "jobname", "title", "position", "jobtitle",
        "岗位名称", "职位", "职位名称", "岗位",
    ),
    "job_url": (
        "job_url", "url", "link", "jobdetail", "detail_url", "detailurl", "joburl", "href",
        "岗位链接", "链接", "详情",
    ),
    "city": (
        "city", "city_name", "cityname", "address", "workplace", "jobarea", "location",
        "城市", "工作地点", "地点",
    ),
    "salary_text": (
        "salary_text", "salary", "salarydesc", "pay", "compensation", "salaryrange",
        "薪资", "薪资范围", "工资",
    ),
    "experience_text": (
        "experience_text", "experience", "workyear", "work_year", "exp",
        "经验", "工作经验", "年限",
    ),
    "education_text": (
        "education_text", "education", "degree", "edu",
        "学历", "学历要求",
    ),
    "jd_text": (
        "jd_text", "jd", "description", "job_description", "jobdescription",
        "detail", "content", "desc", "requirement", "responsibilities",
        "职位描述", "岗位描述", "岗位职责", "任职要求", "工作职责", "描述",
    ),
    "published_text": (
        "published_text", "published", "publish_time", "publishtime", "date", "time",
        "发布时间", "发布日期", "更新时间",
    ),
}

# 面向 extra 的键：非规范字段全部保留（含大小写原样）。
_NORM_KEYS = {alias for aliases in FIELD_ALIASES.values() for alias in aliases}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_coerce_text(item) for item in value]
        return "、".join(part for part in parts if part)
    return str(value).strip()


def _pick(raw: dict[str, Any], aliases: tuple[str, ...]) -> str:
    lowered = {str(key).lower(): value for key, value in raw.items()}
    for alias in aliases:
        if alias in lowered:
            text = _coerce_text(lowered[alias])
            if text:
                return text
    return ""


def normalize_raw_job(payload: RawJobPayload) -> NormalizedJob:
    """容错提取规范字段；原文在 RawJobPayload.raw 中完整保留。"""

    raw = payload.raw if isinstance(payload.raw, dict) else {}
    values: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        values[canonical] = _pick(raw, aliases)

    extra = {
        str(key): value
        for key, value in raw.items()
        if str(key).lower() not in _NORM_KEYS
    }
    return NormalizedJob(**values, extra=extra)


def candidate_source_key(payload: RawJobPayload) -> str:
    """返回来源键；空缺时以原文内容指纹兜底（稳定去重）。"""

    if payload.source_key.strip():
        return payload.source_key.strip()[:255]
    digest = hashlib.sha256(
        json.dumps(payload.raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"auto:{digest}"


def raw_payload_to_json(payload: RawJobPayload) -> str:
    return json.dumps(
        {"source": payload.source, "source_key": payload.source_key, "raw": payload.raw},
        ensure_ascii=False, sort_keys=True,
    )
