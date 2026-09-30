"""候选池仓储：摄取去重、状态流转、画像读写（真实 SQLite）。"""
import pytest

from offerpilot.db import init_database
from offerpilot.discovery.contracts import (
    CandidateScore,
    DimensionScore,
    DiscoveryProfile,
    RawJobPayload,
)
from offerpilot.discovery.repository import CandidateNotFound, DiscoveryRepository
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def _score(total: float = 4.2, grade: str = "A") -> CandidateScore:
    breakdown = tuple(
        DimensionScore(dimension=dim, score=4.0, reason="r") for dim in (
            "tech_match", "salary", "outlook", "stability", "growth", "intensity", "commute"
        )
    )
    return CandidateScore(breakdown=breakdown, total_score=total, grade=grade, rationale="ok")


def test_should_dedup_when_same_source_and_key_ingested_twice(tmp_path):
    sessions = init_database(tmp_path / "db.sqlite3")
    repository = DiscoveryRepository(sessions)
    payload = RawJobPayload(source="manual", source_key="k1", raw={"company_name": "甲公司", "position_name": "岗A"})
    first = repository.ingest([payload])
    second = repository.ingest([RawJobPayload(source="manual", source_key="k1", raw={"company_name": "甲公司", "position_name": "岗A(更新)"})])
    assert len(first) == 1
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["position_name"] == "岗A(更新)"
    assert len(repository.list_candidates()) == 1


def test_should_allow_same_key_across_different_sources(tmp_path):
    sessions = init_database(tmp_path / "db.sqlite3")
    repository = DiscoveryRepository(sessions)
    rows = repository.ingest([
        RawJobPayload(source="manual", source_key="same", raw={"company_name": "甲"}),
        RawJobPayload(source="crawler:zhipin", source_key="same", raw={"company_name": "乙"}),
    ])
    assert len(rows) == 2


def test_should_track_scored_and_promoted_status(tmp_path):
    sessions = init_database(tmp_path / "db.sqlite3")
    repository = DiscoveryRepository(sessions)
    (candidate,) = repository.ingest([RawJobPayload(source="manual", source_key="k", raw={"company_name": "甲"})])
    repository.save_score(candidate["id"], _score(), profile_fingerprint="fp1")
    assert repository.get_candidate(candidate["id"])["status"] == "scored"
    application = ApplicationsRepository(sessions).create(
        ApplicationCreate(company_name="甲", position_name="岗")
    )
    repository.link_promotion(candidate["id"], application_id=application.id)
    updated = repository.get_candidate(candidate["id"])
    assert updated["status"] == "promoted"
    assert updated["promoted_application_id"] == application.id
    assert repository.list_scores(candidate["id"])[0]["grade"] == "A"


def test_should_raise_when_candidate_missing(tmp_path):
    sessions = init_database(tmp_path / "db.sqlite3")
    repository = DiscoveryRepository(sessions)
    with pytest.raises(CandidateNotFound):
        repository.get_candidate(999)


def test_should_upsert_profile_as_singleton(tmp_path):
    sessions = init_database(tmp_path / "db.sqlite3")
    repository = DiscoveryRepository(sessions)
    assert repository.get_profile() is None
    repository.upsert_profile(DiscoveryProfile(cities=("武汉",), directions=("AI应用",), red_lines=("外包",)))
    repository.upsert_profile(DiscoveryProfile(cities=("武汉", "深圳"), salary_expectation="25-45K"))
    profile = repository.get_profile()
    assert profile is not None
    assert profile["cities"] == ["武汉", "深圳"]
    assert profile["salary_expectation"] == "25-45K"
    assert profile["red_lines"] == []
