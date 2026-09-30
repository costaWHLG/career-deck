"""手动投喂 adapter：JD 粘贴/结构化输入（任何路线都保留的手动入口）。"""
from __future__ import annotations

import hashlib
from typing import Any

from offerpilot.discovery.contracts import RawJobPayload

MANUAL_SOURCE_NAME = "manual"


class ManualSourceAdapter:
    """接受用户投喂的岗位原文（JD 文本或结构化字段），不访问外部网络。"""

    name = MANUAL_SOURCE_NAME

    def fetch(self, query: dict[str, Any]) -> list[RawJobPayload]:
        items = query.get("jobs")
        if not isinstance(items, list):
            items = [query]
        payloads: list[RawJobPayload] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw = dict(item)
            source_key = str(raw.pop("source_key", "") or "").strip()
            if not source_key:
                digest = hashlib.sha256(
                    "|".join(
                        str(raw.get(key, "")) for key in ("company_name", "position_name", "job_url")
                    ).encode("utf-8")
                ).hexdigest()
                source_key = f"manual:{digest}"
            payloads.append(RawJobPayload(source=self.name, source_key=source_key, raw=raw))
        return payloads
