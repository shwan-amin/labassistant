"""Build an API app with one answered check, for marker and dashboard tests."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from labassistant.api.app import create_app
from labassistant.config import Settings
from labassistant.llm import FakeLLMClient
from tests.context_helpers import find_line, load_lab

ROOT = Path(__file__).parent.parent
TOKEN = "marker-secret"


def seeded_lab():
    return [
        f.model_copy(update={"content": f.content.replace("count = 0", "count = 1")})
        if f.path == "metrics.py"
        else f
        for f in load_lab("file_tree")
    ]


def app_with_answered_check(
    tmp_path: Path, marker_token: str | None = TOKEN
) -> tuple[TestClient, str]:
    lab = seeded_lab()
    line = find_line(lab, "metrics.py", "count = 1")
    gap = {
        "concept_id": "base_case",
        "misconception_id": "base_case_wrong_value",
        "confidence": "high",
        "evidence": [{"path": "metrics.py", "start_line": line, "end_line": line, "test_ids": []}],
        "rationale": "MARKER ONLY rationale.",
    }
    note = {
        "category": "naming",
        "path": "metrics.py",
        "start_line": line,
        "end_line": line,
        "explanation": "Name the counter.",
    }
    fake = FakeLLMClient(
        [
            FakeLLMClient.text(json.dumps({"concept_gaps": [gap], "quality_notes": [note]})),
            FakeLLMClient.text(
                json.dumps(
                    {
                        "questions": [
                            {"gap_index": 0, "question": "What is returned for an empty directory?"}
                        ]
                    }
                )
            ),
            FakeLLMClient.text(
                json.dumps({"verdict": "confirmed", "rationale": "MARKER ONLY judgement."})
            ),
        ]
    )
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "marker.db",
        processed_materials_dir=tmp_path / "processed",
        materials_dir=ROOT / "materials",
        knowledge_dir=ROOT / "knowledge",
        api_allowed_hosts=["testserver"],
        marker_token=marker_token,
    )
    api = TestClient(create_app(settings, client=fake))
    body = {
        "files": [f.model_dump() for f in lab],
        "selected_path": "metrics.py",
        "selection": {"start": line - 4, "end": line + 3},
        "student_id": "alice",
    }
    session_id = api.post("/checks", json=body).json()["session"]["session_id"]
    api.post(f"/checks/{session_id}/answers", json={"gap_index": 0, "answer": "It returns one."})
    return api, session_id
