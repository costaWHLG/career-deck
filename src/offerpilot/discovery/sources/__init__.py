"""数据源 adapter 注册表。抓取行为只发生在 adapter 内部（ADR 0013 §2.1）。"""
from __future__ import annotations

from offerpilot.discovery.contracts import SourceAdapter
from offerpilot.discovery.sources.manual import ManualSourceAdapter


def build_default_adapters() -> list[SourceAdapter]:
    """首批 adapter：手动投喂。websearch/crawler 在 P2/P3 加入。"""

    return [ManualSourceAdapter()]
