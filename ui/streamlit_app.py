"""Lab Assistant dev and marker dashboard.

    uv run streamlit run ui/streamlit_app.py

Talks only to the backend API (start it with `uv run labassistant-api`). Marker
views need MARKER_TOKEN set on the backend and entered here.
"""

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from labassistant.marker.views import concept_map_dot, context_rows, review_summary, usage_rows

st.set_page_config(page_title="Lab Assistant dashboard", layout="wide")


class Backend:
    """Minimal API client. Tests put a pre-built client in st.session_state["http"]."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def get(self, path: str, **params: Any) -> Any:
        response = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()

    def put(self, path: str, body: dict) -> Any:
        response = self.http.put(path, json=body)
        response.raise_for_status()
        return response.json()


def backend() -> Backend:
    if "http" in st.session_state:
        return Backend(st.session_state["http"])
    url = st.sidebar.text_input(
        "Backend URL", os.environ.get("LABASSISTANT_BACKEND_URL", "http://127.0.0.1:8000")
    )
    token = st.sidebar.text_input(
        "Marker token", os.environ.get("MARKER_TOKEN", ""), type="password"
    )
    return Backend(httpx.Client(base_url=url, headers={"X-Marker-Token": token}, timeout=30))


def show_error(error: Exception) -> None:
    if isinstance(error, httpx.HTTPStatusError):
        try:
            detail = error.response.json().get("detail", error.response.text)
        except ValueError:
            detail = error.response.text
        st.error(f"Backend returned {error.response.status_code}: {detail}")
    else:
        st.error(f"Can't reach the backend ({error}). Start it with `uv run labassistant-api`.")


def sessions_page(api: Backend) -> None:
    sessions = api.get("/marker/sessions")
    if not sessions:
        st.info("No checks yet. Run one from the VS Code extension.")
        return
    st.dataframe(pd.DataFrame(sessions), hide_index=True, width="stretch")

    labels = {
        f"{s['created_at']} · {s['student_id']} · {s['selected_path']}:{s['selection']}": s["id"]
        for s in sessions
    }
    session_id = labels[st.selectbox("Open a check", list(labels))]
    detail = api.get(f"/marker/sessions/{session_id}")
    session, reviews = detail["session"], detail["reviews"]
    diagnosis = session["diagnosis"]

    st.subheader("Context the model saw")
    summary = diagnosis["context_summary"]
    st.caption(
        f"Mode `{summary.get('mode')}` · budget {summary.get('token_budget')} · "
        f"used {summary.get('used_tokens')} (estimated)"
    )
    st.dataframe(pd.DataFrame(context_rows(summary)), hide_index=True, width="stretch")
    if summary.get("skipped_files"):
        with st.expander(f"{len(summary['skipped_files'])} skipped files"):
            st.dataframe(pd.DataFrame(summary["skipped_files"]), hide_index=True)

    st.subheader("Token usage (reported by the API)")
    st.dataframe(pd.DataFrame(usage_rows(session)), hide_index=True)
    st.caption(
        f"Model `{diagnosis['model']}` · {diagnosis['turns']} diagnosis calls · "
        f"{len(diagnosis['tool_calls'])} tool calls"
    )

    if diagnosis["adjustments"] or session["adjustments"]:
        with st.expander("Validation and leak-check adjustments"):
            st.dataframe(
                pd.DataFrame(diagnosis["adjustments"] + session["adjustments"]), hide_index=True
            )
    if diagnosis["tool_calls"]:
        with st.expander("Tool calls (internal: probe code is never shown to students)"):
            for call in diagnosis["tool_calls"]:
                st.write(call["input"] or "all tests", "→", call["status"])
                if call.get("probe_code"):
                    st.code(call["probe_code"], language="python")

    marker_view(api, session_id, session, reviews)


def marker_view(api: Backend, session_id: str, session: dict, reviews: list[dict]) -> None:
    st.subheader("Marker view")
    counts = review_summary(session, reviews)
    st.caption(" · ".join(f"{k}: {v}" for k, v in counts.items()))
    graph = api.get("/marker/concepts")
    concept_ids = [c["id"] for c in graph["concepts"]]
    existing = {(r["item_type"], r["item_index"]): r for r in reviews}
    new_reviews: list[dict] = []

    for gap_state in session["gaps"]:
        gap, index = gap_state["gap"], gap_state["index"]
        with st.container(border=True):
            st.markdown(
                f"**Gap {index}: `{gap['concept_id']}` / `{gap['misconception_id']}`** · "
                f"confidence {gap['confidence']} · status {gap_state['status']}"
            )
            st.write(
                "Evidence:",
                ", ".join(
                    f"{e['path']}:{e['start_line']}-{e['end_line']} {e['test_ids']}"
                    for e in gap["evidence"]
                ),
            )
            st.write("Rationale (marker only):", gap["rationale"] or "_(removed by leak check)_")
            if gap_state.get("question"):
                st.write(f"Question ({gap_state['question_source']}):", gap_state["question"])
            if gap_state.get("answer"):
                st.write("Student answer:", gap_state["answer"])
                st.write("Answer judgement (marker only):", gap_state["evaluation_rationale"])
            new_reviews.append(
                review_controls("gap", index, existing.get(("gap", index)), graph, concept_ids)
            )

    for index, note in enumerate(session["diagnosis"]["quality_notes"]):
        with st.container(border=True):
            st.markdown(
                f"**Note {index}: {note['category']}** · "
                f"{note['path']}:{note['start_line']}-{note['end_line']}"
            )
            st.write(note["explanation"])
            new_reviews.append(
                review_controls("note", index, existing.get(("note", index)), graph, concept_ids)
            )

    new_reviews = [r for r in new_reviews if r is not None]
    if new_reviews and st.button("Save reviews", type="primary"):
        try:
            result = api.put(f"/marker/sessions/{session_id}/reviews", {"reviews": new_reviews})
            st.success(f"Saved {result['saved']} reviews.")
        except httpx.HTTPError as error:
            show_error(error)


def review_controls(
    item_type: str, index: int, existing: dict | None, graph: dict, concept_ids: list[str]
) -> dict | None:
    options = ["(not reviewed)", "accept", "reject"] + (["override"] if item_type == "gap" else [])
    current = existing["decision"] if existing else "(not reviewed)"
    key = f"{item_type}-{index}"
    decision = st.radio(
        "Decision", options, index=options.index(current), key=f"{key}-decision", horizontal=True
    )
    if decision == "(not reviewed)":
        return None
    review: dict[str, Any] = {"item_type": item_type, "item_index": index, "decision": decision}
    if decision == "override":
        default = existing.get("concept_id") if existing else None
        concept_id = st.selectbox(
            "Actual concept",
            concept_ids,
            index=concept_ids.index(default) if default in concept_ids else 0,
            key=f"{key}-concept",
        )
        concept = next(c for c in graph["concepts"] if c["id"] == concept_id)
        misconceptions = ["(none)"] + [m["id"] for m in concept["misconceptions"]]
        misconception = st.selectbox(
            "Actual misconception", misconceptions, key=f"{key}-misconception"
        )
        review["concept_id"] = concept_id
        review["misconception_id"] = None if misconception == "(none)" else misconception
    review["comment"] = st.text_input(
        "Comment", existing.get("comment", "") if existing else "", key=f"{key}-comment"
    )
    return review


def learners_page(api: Backend) -> None:
    students = api.get("/marker/learners")
    if not students:
        st.info("No learners yet.")
        return
    student = st.selectbox("Student", students)
    concept_map = api.get(f"/learners/{student}/mastery")
    left, right = st.columns([1, 1])
    with left:
        st.dataframe(
            pd.DataFrame(
                [{"concept": n["name"], "state": n["state"]} for n in concept_map["nodes"]]
            ),
            hide_index=True,
        )
    with right:
        st.graphviz_chart(concept_map_dot(concept_map))
    st.subheader("History")
    events = api.get(f"/marker/learners/{student}/events")
    if events:
        st.dataframe(pd.DataFrame(events), hide_index=True, width="stretch")
    else:
        st.caption("No events.")


st.title("Lab Assistant dashboard")
page = st.sidebar.radio("View", ["Checks and marker view", "Learner model"])
api = backend()
try:
    if page == "Checks and marker view":
        sessions_page(api)
    else:
        learners_page(api)
except httpx.HTTPError as error:
    show_error(error)
