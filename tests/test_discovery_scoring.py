"""发现层评分：权重、评级、红线、信息不足标注（ADR 0013 §2.2）。"""
import json

from offerpilot.ai.types import Assistant, Message
from offerpilot.discovery.contracts import DiscoveryProfile, NormalizedJob
from offerpilot.discovery.scoring import (
    DIMENSION_ORDER,
    DIMENSION_WEIGHTS,
    CandidateScoringService,
)


class StubCompleter:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.messages: list[Message] = []

    def complete_readonly_draft(self, messages: list[Message], *, timeout_seconds: float):
        self.messages = list(messages)
        return Assistant(content=json.dumps(self.payload, ensure_ascii=False))


def _dimensions(**overrides: dict) -> dict:
    dims = {
        dimension: {"score": 3, "reason": "中性", "information_lacking": False}
        for dimension in DIMENSION_ORDER
    }
    dims.update(overrides)
    return dims


def _job() -> NormalizedJob:
    return NormalizedJob(
        company_name="长江存储", position_name="AI应用开发工程师", city="武汉",
        salary_text="25-35K", jd_text="负责 AI 应用研发",
    )


def test_should_compute_weighted_total_when_model_scores_each_dimension():
    completer = StubCompleter({
        "dimensions": _dimensions(
            tech_match={"score": 4, "reason": "技术栈高度重合", "information_lacking": False},
            salary={"score": 3, "reason": "区间下沿", "information_lacking": False},
        ),
        "rationale": "值得投", "red_line_hits": [],
    })
    score = CandidateScoringService(completer).score(_job(), DiscoveryProfile())
    expected = round(4 * 0.25 + 3 * 0.20 + 3 * 0.15 + 3 * 0.10 * 4, 2)
    assert score.total_score == expected
    assert score.grade == "B"
    assert len(score.breakdown) == 7
    assert {dim.dimension for dim in score.breakdown} == set(DIMENSION_ORDER)


def test_should_grade_c_when_red_lines_hit_even_with_high_total():
    completer = StubCompleter({
        "dimensions": _dimensions(**{dim: {"score": 5, "reason": "好", "information_lacking": False} for dim in DIMENSION_ORDER}),
        "rationale": "强匹配", "red_line_hits": ["薪资低于底线"],
    })
    score = CandidateScoringService(completer).score(_job(), DiscoveryProfile())
    assert score.total_score == 5.0
    assert score.grade == "C"
    assert score.red_line_hits == ("薪资低于底线",)


def test_should_mark_information_lacking_when_model_flags_or_omits_score():
    completer = StubCompleter({
        "dimensions": _dimensions(commute={"score": 3, "reason": "信息不足：JD未说明办公地址", "information_lacking": True}),
        "rationale": "待补充", "red_line_hits": [],
    })
    score = CandidateScoringService(completer).score(_job(), DiscoveryProfile())
    commute = next(dim for dim in score.breakdown if dim.dimension == "commute")
    assert commute.is_information_lacking
    assert "信息不足" in commute.reason


def test_should_recover_from_invalid_model_output_with_neutral_scores():
    class BadCompleter:
        def complete_readonly_draft(self, messages, *, timeout_seconds):
            return Assistant(content="不是 JSON")

    score = CandidateScoringService(BadCompleter()).score(_job(), DiscoveryProfile())
    assert score.total_score == 3.0
    assert all(dim.is_information_lacking for dim in score.breakdown)


def test_should_send_profile_and_truncated_jd_to_model():
    profile = DiscoveryProfile(
        resume_text="A" * 3000, cities=("武汉",), directions=("AI应用",), red_lines=("人力外包",)
    )
    completer = StubCompleter({"dimensions": _dimensions(), "rationale": "", "red_line_hits": []})
    CandidateScoringService(completer).score(_job(), profile)
    payload = json.loads(completer.messages[1].content)
    assert payload["candidate_profile"]["cities"] == ["武汉"]
    assert payload["candidate_profile"]["red_lines"] == ["人力外包"]
    assert len(payload["candidate_profile"]["resume_text"]) <= 1101
    assert DIMENSION_WEIGHTS["tech_match"] == 0.25
