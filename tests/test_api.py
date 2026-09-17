import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from labassistant.api.app import create_app
from labassistant.config import Settings
from labassistant.llm import FakeLLMClient
from labassistant.llm.gemini_client import DailyQuotaExceededError
from tests.context_helpers import find_line, load_lab

ROOT = Path(__file__).parent.parent
FAILING_TEST = "tests/test_metrics.py::test_count_files_ignores_directories"
PROBE_TEST = "test_labassistant_probe.py::test_empty"


class ScriptedClient(FakeLLMClient):
    """A fake LLM that can also raise an exception instead of answering."""

    def complete(self, **kwargs):
        if self._responses and isinstance(self._responses[0], Exception):
            self.calls.append(kwargs)
            raise self._responses.pop(0)
        return super().complete(**kwargs)


@pytest.fixture(scope="module")
def lab():
    return [
        f.model_copy(update={"content": f.content.replace("count = 0", "count = 1")})
        if f.path == "metrics.py"
        else f
        for f in load_lab("file_tree")
    ]


@pytest.fixture
def settings(tmp_path) -> Settings:
    thumbnails = tmp_path / "processed" / "thumbnails" / "mit6_0001_f16_lec6"
    thumbnails.mkdir(parents=True)
    (thumbnails / "slide-010.png").write_bytes(b"\x89PNG fake")
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.db",
        processed_materials_dir=tmp_path / "processed",
        materials_dir=ROOT / "materials",
        knowledge_dir=ROOT / "knowledge",
        api_allowed_hosts=["testserver", "localhost"],
        max_request_bytes=500_000,
    )


def make_client(settings: Settings, responses: list) -> tuple[TestClient, ScriptedClient]:
    fake = ScriptedClient(responses)
    return TestClient(create_app(settings, client=fake)), fake


def check_body(lab, **overrides) -> dict:
    line = find_line(lab, "metrics.py", "count = 1")
    body = {
        "files": [f.model_dump() for f in lab],
        "selected_path": "metrics.py",
        "selection": {"start": line - 4, "end": line + 3},
        "explanation": "Counts files recursively.",
        "student_id": "alice",
    }
    body.update(overrides)
    return body


def diagnosis(lab) -> FakeLLMClient:
    line = find_line(lab, "metrics.py", "count = 1")
    gap = {
        "concept_id": "base_case",
        "misconception_id": "base_case_wrong_value",
        "confidence": "high",
        "evidence": [
            {"path": "metrics.py", "start_line": line, "end_line": line, "test_ids": [FAILING_TEST]}
        ],
        "rationale": "MARKER ONLY: count should start at zero.",
    }
    note = {
        "category": "readability",
        "path": "metrics.py",
        "start_line": line,
        "end_line": line,
        "explanation": "A comment explaining the starting count would help.",
    }
    return FakeLLMClient.text(json.dumps({"concept_gaps": [gap], "quality_notes": [note]}))


QUESTION = FakeLLMClient.text(
    json.dumps(
        {
            "questions": [
                {"gap_index": 0, "question": "What does count_files return for an empty directory?"}
            ]
        }
    )
)


def verdict(value: str) -> FakeLLMClient:
    return FakeLLMClient.text(
        json.dumps({"verdict": value, "rationale": "MARKER ONLY verdict note."})
    )


def assert_student_safe(response) -> None:
    text = response.text
    for secret in ("MARKER ONLY", "base_case_wrong_value", PROBE_TEST, "probe_code", "rationale"):
        assert secret not in text, secret


# --- full flow ---


def test_full_check_flow(settings, lab) -> None:
    api, fake = make_client(settings, [diagnosis(lab), QUESTION, verdict("confirmed")])

    started = api.post("/checks", json=check_body(lab))
    assert started.status_code == 200, started.text
    assert_student_safe(started)
    data = started.json()
    session_id = data["session"]["session_id"]
    assert data["next_question"] == {
        "gap_index": 0,
        "concept_name": "Base case",
        "question": "What does count_files return for an empty directory?",
    }
    [gap] = data["session"]["gaps"]
    assert gap["status"] == "suspected" and gap["evidence"][0]["test_ids"] == [FAILING_TEST]
    assert data["session"]["quality_notes"][0]["category"] == "readability"

    fetched = api.get(f"/checks/{session_id}")
    assert fetched.status_code == 200 and fetched.json() == data

    blocked = api.get(f"/checks/{session_id}/gaps/0/materials")
    assert blocked.status_code == 409  # not confirmed yet

    answered = api.post(
        f"/checks/{session_id}/answers", json={"gap_index": 0, "answer": "It returns 1."}
    )
    assert answered.status_code == 200, answered.text
    assert_student_safe(answered)
    result = answered.json()
    assert result["status"] == "confirmed"
    assert result["mastery_change"] == {
        "concept_id": "base_case",
        "old_state": "unknown",
        "new_state": "emerging",
    }
    assert result["complete"] and result["next_question"] is None
    kinds = {m["kind"]: m for m in result["materials"]}
    assert kinds["lecture"]["url"].endswith("#t=511")  # 8:31, the reviewed base case moment
    assert kinds["slide"]["slide_number"] == 10
    assert kinds["slide"]["thumbnail_url"] == "/materials/thumbnails/mit6_0001_f16_lec6/10"
    assert "MIT OpenCourseWare" in kinds["slide"]["attribution"]

    materials = api.get(f"/checks/{session_id}/gaps/0/materials")
    assert materials.status_code == 200 and materials.json() == result["materials"]

    thumbnail = api.get(kinds["slide"]["thumbnail_url"])
    assert thumbnail.status_code == 200 and thumbnail.headers["content-type"] == "image/png"

    concept_map = api.get("/learners/alice/mastery").json()
    states = {node["id"]: node["state"] for node in concept_map["nodes"]}
    assert states["base_case"] == "emerging" and states["call_stack"] == "unknown"
    assert {"source": "recursive_decomposition", "target": "base_case"} in concept_map["edges"]
    assert len(fake.calls) == 3


def test_skip_questioning_returns_no_question_and_allows_materials(settings, lab) -> None:
    api, fake = make_client(settings, [diagnosis(lab)])
    data = api.post("/checks", json=check_body(lab, skip_questioning=True)).json()

    assert data["next_question"] is None
    assert data["session"]["gaps"][0]["status"] == "shown"
    assert api.get(f"/checks/{data['session']['session_id']}/gaps/0/materials").status_code == 200
    assert len(fake.calls) == 1


# --- errors ---


def test_selection_outside_file_is_422(settings, lab) -> None:
    api, _ = make_client(settings, [])
    response = api.post("/checks", json=check_body(lab, selection={"start": 500, "end": 501}))
    assert response.status_code == 422
    assert "outside metrics.py" in response.json()["detail"]


def test_request_validation_errors_are_422(settings, lab) -> None:
    api, _ = make_client(settings, [])
    assert api.post("/checks", json=check_body(lab, student_id="bad id!")).status_code == 422
    assert api.post("/checks", json={"files": []}).status_code == 422


def test_request_too_large_is_413(settings, lab) -> None:
    api, _ = make_client(settings, [])
    big = check_body(
        lab, files=[{"path": "big.py", "content": "x" * 600_000}, *check_body(lab)["files"]]
    )
    assert api.post("/checks", json=big).status_code == 413


def test_unknown_session_and_gap_are_404(settings, lab) -> None:
    api, _ = make_client(settings, [diagnosis(lab), QUESTION])
    assert api.get("/checks/does-not-exist").status_code == 404
    session_id = api.post("/checks", json=check_body(lab)).json()["session"]["session_id"]
    assert api.get(f"/checks/{session_id}/gaps/7/materials").status_code == 404
    assert (
        api.post(f"/checks/{session_id}/answers", json={"gap_index": 7, "answer": "x"}).status_code
        == 409
    )


def test_answering_twice_is_409(settings, lab) -> None:
    api, _ = make_client(settings, [diagnosis(lab), QUESTION, verdict("cleared")])
    session_id = api.post("/checks", json=check_body(lab)).json()["session"]["session_id"]
    first = api.post(f"/checks/{session_id}/answers", json={"gap_index": 0, "answer": "Zero."})
    assert first.status_code == 200 and first.json()["materials"] == []  # cleared: no materials
    again = api.post(f"/checks/{session_id}/answers", json={"gap_index": 0, "answer": "Zero."})
    assert again.status_code == 409


def test_unusable_llm_output_is_502(settings, lab) -> None:
    api, _ = make_client(settings, [FakeLLMClient.text("nope"), FakeLLMClient.text("still nope")])
    response = api.post("/checks", json=check_body(lab))
    assert response.status_code == 502
    assert "diagnosis failed" in response.json()["detail"]


def test_quota_and_service_errors_are_503(settings, lab) -> None:
    api, _ = make_client(settings, [DailyQuotaExceededError("daily request quota used up")])
    assert api.post("/checks", json=check_body(lab)).status_code == 503

    api, _ = make_client(
        settings, [genai_errors.ServerError(500, {"error": {"code": 500, "message": "boom"}})]
    )
    assert "LLM service error" in api.post("/checks", json=check_body(lab)).json()["detail"]


def test_missing_api_key_is_503_but_health_works(settings, lab) -> None:
    keyless = settings.model_copy(update={"gemini_api_key": None, "llm_provider": "gemini"})
    api = TestClient(create_app(keyless))

    assert api.get("/health").json()["status"] == "ok"
    response = api.post("/checks", json=check_body(lab))
    assert response.status_code == 503 and "GEMINI_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    "path",
    [
        "/materials/thumbnails/mit6_0001_f16_lec6/99",
        "/materials/thumbnails/..%2F..%2Fsecrets/1",
        "/materials/thumbnails/MIT/10",
        "/materials/thumbnails/mit6_0001_f16_lec6/0",
    ],
)
def test_thumbnail_rejects_missing_and_unsafe_paths(settings, path) -> None:
    api, _ = make_client(settings, [])
    assert api.get(path).status_code == 404


def test_other_host_names_are_rejected(settings) -> None:
    api, _ = make_client(settings, [])
    assert api.get("/health", headers={"host": "evil.example.com"}).status_code == 400
    assert api.get("/health", headers={"host": "localhost"}).status_code == 200


def test_openapi_docs_describe_endpoints(settings) -> None:
    api, _ = make_client(settings, [])
    spec = api.get("/openapi.json").json()
    assert {"/checks", "/checks/{session_id}/answers", "/learners/{student_id}/mastery"} <= set(
        spec["paths"]
    )
    assert "503" in spec["paths"]["/checks"]["post"]["responses"]
