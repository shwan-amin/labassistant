from pathlib import Path

import pytest

from labassistant.marker.views import concept_map_dot, context_rows, review_summary, usage_rows
from tests.marker_helpers import TOKEN, app_with_answered_check

APP_PATH = str(Path(__file__).parent.parent / "ui" / "streamlit_app.py")


# --- view helpers ---


def test_context_rows_and_usage_rows() -> None:
    summary = {
        "items": [
            {"kind": "selection", "title": "Selected code", "tokens": 50, "status": "included"}
        ]
    }
    assert context_rows(summary) == [
        {"kind": "selection", "item": "Selected code", "tokens": 50, "status": "included"}
    ]

    session = {
        "diagnosis": {
            "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 40}
        },
        "question_usage": {"input_tokens": 20, "output_tokens": 5},
        "answer_usage": {},
    }
    rows = usage_rows(session)
    assert rows[-1] == {"step": "total", "input": 120, "cached input": 40, "output": 15}


def test_concept_map_dot() -> None:
    concept_map = {
        "nodes": [
            {"id": "a", "name": 'Say "hi"', "state": "secure"},
            {"id": "b", "name": "B", "state": "unknown"},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    dot = concept_map_dot(concept_map)
    assert '"a" -> "b";' in dot
    assert "#2e9e4f" in dot and "Say 'hi'" in dot


def test_review_summary() -> None:
    session = {"gaps": [{}, {}], "diagnosis": {"quality_notes": [{}]}}
    reviews = [{"decision": "accept"}, {"decision": "override"}]
    assert review_summary(session, reviews) == {
        "items": 3,
        "reviewed": 2,
        "accepted": 1,
        "overridden": 1,
        "rejected": 0,
    }


# --- the Streamlit app, run headless against the real API app ---


@pytest.fixture
def dashboard(tmp_path):
    from streamlit.testing.v1 import AppTest

    api, session_id = app_with_answered_check(tmp_path)
    api.headers["X-Marker-Token"] = TOKEN
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.session_state["http"] = api
    return app, api, session_id


def test_checks_page_shows_context_usage_and_marker_view(dashboard) -> None:
    app, _, _ = dashboard
    app.run()

    assert not app.exception, app.exception
    text = " ".join(m.value for m in app.markdown) + " ".join(c.value for c in app.caption)
    assert "MARKER ONLY rationale." in text
    assert "Gap 0" in text and "Note 0" in text
    assert len(app.dataframe) >= 3  # sessions, context items, usage
    assert [r.label for r in app.radio].count("Decision") == 2  # one per gap and note


def test_saving_a_review_from_the_dashboard(dashboard) -> None:
    app, api, session_id = dashboard
    app.run()
    app.radio(key="gap-0-decision").set_value("accept").run()
    app.radio(key="note-0-decision").set_value("reject").run()
    app.button[0].click().run()

    assert not app.exception, app.exception
    assert "Saved 2 reviews." in [s.value for s in app.success]
    stored = api.get(f"/marker/sessions/{session_id}").json()["reviews"]
    assert {(r["item_type"], r["decision"]) for r in stored} == {
        ("gap", "accept"),
        ("note", "reject"),
    }


def test_learner_page(dashboard) -> None:
    app, _, _ = dashboard
    app.run()
    app.sidebar.radio[0].set_value("Learner model").run()

    assert not app.exception, app.exception
    assert app.selectbox[0].value == "alice"
    assert len(app.dataframe) == 2  # mastery table and history
