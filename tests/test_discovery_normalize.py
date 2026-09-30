"""发现层归一化容错：多源异构字段 -> 规范字段稳定，原文保留（ADR 0013 §2.1）。"""
from offerpilot.discovery.contracts import RawJobPayload
from offerpilot.discovery.normalize import (
    candidate_source_key,
    normalize_raw_job,
    raw_payload_to_json,
)


def test_should_map_common_aliases_when_sources_use_different_field_names():
    zhipin_style = RawJobPayload(
        source="crawler:zhipin",
        source_key="u1",
        raw={"jobName": "AI应用开发", "brandName": "某公司", "salaryDesc": "25-35K", "jobArea": "武汉"},
    )
    liepin_style = RawJobPayload(
        source="crawler:liepin",
        source_key="u2",
        raw={"title": "AI应用开发工程师", "company": "某公司", "salary": "25-35K", "city": "武汉"},
    )
    first = normalize_raw_job(zhipin_style)
    second = normalize_raw_job(liepin_style)
    assert first.position_name == "AI应用开发"
    assert first.company_name == "某公司"
    assert first.salary_text == "25-35K"
    assert first.city == "武汉"
    assert second.position_name == "AI应用开发工程师"
    assert second.city == "武汉"


def test_should_fill_empty_values_when_fields_are_missing():
    normalized = normalize_raw_job(RawJobPayload(source="manual", source_key="k", raw={"company_name": "某公司"}))
    assert normalized.company_name == "某公司"
    assert normalized.position_name == ""
    assert normalized.jd_text == ""
    assert normalized.extra == {}


def test_should_keep_unknown_fields_in_extra_and_preserve_raw_payload():
    payload = RawJobPayload(
        source="manual",
        source_key="k",
        raw={"company_name": "某公司", "position_name": "岗位", "bossName": "张三", "welfareList": ["双休", "六险"]},
    )
    normalized = normalize_raw_job(payload)
    assert normalized.extra == {"bossName": "张三", "welfareList": ["双休", "六险"]}
    saved = raw_payload_to_json(payload)
    assert "bossName" in saved
    assert candidate_source_key(payload) == "k"


def test_should_generate_stable_source_key_when_missing():
    raw = {"company_name": "某公司", "position_name": "岗位"}
    first = candidate_source_key(RawJobPayload(source="manual", source_key="", raw=raw))
    second = candidate_source_key(RawJobPayload(source="manual", source_key="", raw=raw))
    assert first.startswith("auto:")
    assert first == second


def test_should_accept_list_values_when_platforms_return_tag_arrays():
    normalized = normalize_raw_job(
        RawJobPayload(source="manual", source_key="k", raw={"城市": ["洪山区", "光谷"], "薪资": "面议"})
    )
    assert normalized.city == "洪山区、光谷"
    assert normalized.salary_text == "面议"
