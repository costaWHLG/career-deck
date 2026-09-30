"""发现层 HTTP 全链路：投喂 -> 评分 -> 晋升 -> 幂等复放（ADR 0013 §2.3）。"""
import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app
import offerpilot.api as api_module


class StubCompleter:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_readonly_draft(self, messages, *, timeout_seconds):
        return Assistant(content=json.dumps(self.payload, ensure_ascii=False))


def _score_payload() -> dict:
    dims = {
        dim: {"score": 4, "reason": "匹配良好", "information_lacking": False}
        for dim in ("tech_match", "salary", "outlook", "stability", "growth", "intensity", "commute")
    }
    return {"dimensions": dims, "rationale": "建议投递", "red_line_hits": []}


def _client_with_stub_scoring(tmp_path, monkeypatch, score_payload: dict | None = None):
    stub = StubCompleter(score_payload if score_payload is not None else _score_payload())
    original = api_module.register_discovery_routes

    def register_with_stub(app, sessions, data_dir, completer_factory=None):
        original(app, sessions, data_dir, completer_factory=lambda: stub)

    monkeypatch.setattr(api_module, "register_discovery_routes", register_with_stub)
    return TestClient(create_app(data_dir=tmp_path))


def test_should_ingest_score_promote_candidate_end_to_end(tmp_path, monkeypatch):
    client = _client_with_stub_scoring(tmp_path, monkeypatch)

    ingested = client.post("/api/discovery/candidates", json={
        "company_name": "长江存储",
        "position_name": "AI应用开发工程师",
        "city": "武汉",
        "salary_text": "25-35K",
        "jd_text": "负责 AI 应用研发，精通 Python",
        "job_url": "https://liepin.example/job/1",
    })
    assert ingested.status_code == 201
    candidate = ingested.json()[0]
    candidate_id = candidate["id"]
    assert candidate["status"] == "new"

    scored = client.post(f"/api/discovery/candidates/{candidate_id}/score")
    assert scored.status_code == 201
    score = scored.json()
    assert score["grade"] in ("A", "B", "C")
    assert len(score["breakdown"]) == 7

    promoted = client.post(f"/api/discovery/candidates/{candidate_id}/promote", json={"notes": "首选"})
    assert promoted.status_code == 201
    application_id = promoted.json()["application_id"]
    assert promoted.json()["replayed"] is False

    replay = client.post(f"/api/discovery/candidates/{candidate_id}/promote")
    assert replay.status_code == 201
    assert replay.json()["application_id"] == application_id
    assert replay.json()["replayed"] is True

    detail = client.get(f"/api/discovery/candidates/{candidate_id}").json()
    assert detail["status"] == "promoted"
    assert detail["promoted_application_id"] == application_id

    applications = client.get("/api/applications").json()
    promoted_app = next(item for item in applications if item["id"] == application_id)
    assert promoted_app["company_name"] == "长江存储"
    assert promoted_app["source"] == "discovery"

    jd = client.get(f"/api/applications/{application_id}/job-description").json()
    assert jd["current"]["jd_text"] == "负责 AI 应用研发，精通 Python"


def test_should_grade_c_and_keep_can_promote_when_red_lines_hit(tmp_path, monkeypatch):
    redlined = _score_payload()
    redlined["red_line_hits"] = ["薪资低于底线"]
    client = _client_with_stub_scoring(tmp_path, monkeypatch, redlined)
    candidate_id = client.post("/api/discovery/candidates", json={
        "company_name": "外包公司", "position_name": "驻场开发",
    }).json()[0]["id"]
    score = client.post(f"/api/discovery/candidates/{candidate_id}/score").json()
    assert score["grade"] == "C"
    assert score["red_line_hits"] == ["薪资低于底线"]


def test_should_return_404_when_candidate_missing(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    assert client.get("/api/discovery/candidates/999").status_code == 404
    assert client.post("/api/discovery/candidates/999/promote").status_code == 404


def test_should_reject_unknown_candidate_status(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    ingested = client.post("/api/discovery/candidates", json={"company_name": "甲", "position_name": "岗"})
    candidate_id = ingested.json()[0]["id"]
    response = client.patch(f"/api/discovery/candidates/{candidate_id}/status", json={"status": "unknown"})
    assert response.status_code == 422


def test_should_manage_profile_over_http(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    assert client.get("/api/discovery/profile").json()["cities"] == []
    saved = client.put("/api/discovery/profile", json={
        "cities": ["武汉"], "directions": ["AI应用"], "salary_expectation": "25-45K", "red_lines": ["人力外包"],
    })
    assert saved.status_code == 200
    profile = client.get("/api/discovery/profile").json()
    assert profile["cities"] == ["武汉"]
    assert profile["red_lines"] == ["人力外包"]
