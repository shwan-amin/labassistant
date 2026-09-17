import pytest

from tests.marker_helpers import TOKEN, app_with_answered_check

HEADERS = {"X-Marker-Token": TOKEN}


@pytest.fixture
def app(tmp_path):
    return app_with_answered_check(tmp_path)


def test_marker_endpoints_disabled_without_configured_token(tmp_path) -> None:
    api, session_id = app_with_answered_check(tmp_path, marker_token=None)
    response = api.get(f"/marker/sessions/{session_id}", headers=HEADERS)
    assert response.status_code == 403 and "MARKER_TOKEN" in response.json()["detail"]


@pytest.mark.parametrize("headers", [{}, {"X-Marker-Token": "wrong"}])
def test_marker_endpoints_need_the_right_token(app, headers) -> None:
    api, session_id = app
    for path in (
        "/marker/sessions",
        f"/marker/sessions/{session_id}",
        "/marker/learners",
        "/marker/concepts",
    ):
        assert api.get(path, headers=headers).status_code == 401, path


def test_session_list_and_full_detail(app) -> None:
    api, session_id = app
    [summary] = api.get("/marker/sessions", headers=HEADERS).json()
    assert summary["id"] == session_id and summary["student_id"] == "alice"
    assert (summary["gaps"], summary["quality_notes"], summary["reviewed"]) == (1, 1, 0)
    assert summary["input_tokens"] > 0

    detail = api.get(f"/marker/sessions/{session_id}", headers=HEADERS).json()
    gap = detail["session"]["gaps"][0]
    assert gap["gap"]["rationale"] == "MARKER ONLY rationale."  # markers do see rationales
    assert gap["evaluation_rationale"] == "MARKER ONLY judgement."
    assert detail["session"]["diagnosis"]["context_summary"]["items"]
    assert detail["reviews"] == []
    assert api.get("/marker/sessions/nope", headers=HEADERS).status_code == 404


def test_save_and_update_reviews(app) -> None:
    api, session_id = app
    reviews = [
        {
            "item_type": "gap",
            "item_index": 0,
            "decision": "override",
            "concept_id": "recursive_case",
            "comment": "It's the combine step.",
        },
        {"item_type": "note", "item_index": 0, "decision": "reject"},
    ]
    saved = api.put(
        f"/marker/sessions/{session_id}/reviews", json={"reviews": reviews}, headers=HEADERS
    )
    assert saved.status_code == 200 and saved.json()["saved"] == 2

    update = [{"item_type": "gap", "item_index": 0, "decision": "accept"}]
    api.put(f"/marker/sessions/{session_id}/reviews", json={"reviews": update}, headers=HEADERS)

    stored = api.get(f"/marker/sessions/{session_id}", headers=HEADERS).json()["reviews"]
    assert [(r["item_type"], r["decision"]) for r in stored] == [
        ("gap", "accept"),
        ("note", "reject"),
    ]
    assert api.get("/marker/sessions", headers=HEADERS).json()[0]["reviewed"] == 2


@pytest.mark.parametrize(
    ("review", "message"),
    [
        ({"item_type": "gap", "item_index": 3, "decision": "accept"}, "no gap 3"),
        (
            {"item_type": "gap", "item_index": 0, "decision": "override", "concept_id": "pointers"},
            "unknown concept",
        ),
        (
            {
                "item_type": "gap",
                "item_index": 0,
                "decision": "override",
                "concept_id": "call_stack",
                "misconception_id": "missing_base_case",
            },
            "not a misconception of call_stack",
        ),
        (
            {
                "item_type": "note",
                "item_index": 0,
                "decision": "override",
                "concept_id": "base_case",
            },
            "only concept gaps",
        ),
        ({"item_type": "gap", "item_index": 0, "decision": "override"}, "needs a concept_id"),
    ],
)
def test_invalid_reviews_rejected_and_nothing_saved(app, review, message) -> None:
    api, session_id = app
    good = {"item_type": "note", "item_index": 0, "decision": "accept"}
    response = api.put(
        f"/marker/sessions/{session_id}/reviews", json={"reviews": [good, review]}, headers=HEADERS
    )
    assert response.status_code == 422
    assert message in response.text
    assert api.get(f"/marker/sessions/{session_id}", headers=HEADERS).json()["reviews"] == []


def test_learners_events_and_concepts(app) -> None:
    api, _ = app
    assert api.get("/marker/learners", headers=HEADERS).json() == ["alice"]
    [event] = api.get("/marker/learners/alice/events", headers=HEADERS).json()
    assert (event["concept_id"], event["event"], event["new_state"]) == (
        "base_case",
        "confirmed",
        "emerging",
    )
    assert len(api.get("/marker/concepts", headers=HEADERS).json()["concepts"]) == 7


def test_student_endpoints_still_hide_marker_information(app) -> None:
    api, session_id = app
    assert "MARKER ONLY" not in api.get(f"/checks/{session_id}").text
