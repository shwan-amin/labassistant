"""Marker endpoints: full sessions (including rationales) and review decisions.

These show information students must never see, so every route requires the
X-Marker-Token header to match MARKER_TOKEN. With no token configured the routes
are disabled. Comparison uses hmac.compare_digest to avoid timing leaks.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from labassistant.api.state import AppState
from labassistant.marker.models import Decision, ReviewsRequest
from labassistant.tutoring.models import TutoringSession


def _state(request: Request) -> AppState:
    return request.app.state.lab


def require_marker(request: Request, x_marker_token: str | None = Header(default=None)) -> None:
    expected = _state(request).settings.marker_token
    if not expected:
        raise HTTPException(403, "marker endpoints are disabled: set MARKER_TOKEN on the backend")
    if not x_marker_token or not hmac.compare_digest(x_marker_token, expected):
        raise HTTPException(401, "missing or wrong X-Marker-Token")


router = APIRouter(prefix="/marker", tags=["marker"], dependencies=[Depends(require_marker)])


@router.get("/sessions")
def list_sessions(request: Request, student_id: str | None = None) -> list[dict[str, Any]]:
    state = _state(request)
    summaries = []
    for row in state.store.list_sessions(student_id):
        data = state.store.load_session(row["id"]) or {}
        session = TutoringSession.model_validate(data)
        usage = session.total_usage
        summaries.append(
            {
                **row,
                "selected_path": session.selected_path,
                "selection": f"{session.selection.start}-{session.selection.end}",
                "gaps": len(session.gaps),
                "quality_notes": len(session.quality_notes),
                "leaks_removed": session.diagnosis.leaks_removed
                + sum(
                    a.action == "question_replaced" and "leak_removed" in a.detail
                    for a in session.adjustments
                ),
                "input_tokens": usage.total_input_tokens,
                "output_tokens": usage.output_tokens,
                "reviewed": len(state.store.get_reviews(row["id"])),
            }
        )
    return summaries


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict[str, Any]:
    state = _state(request)
    data = state.store.load_session(session_id)
    if data is None:
        raise HTTPException(404, "session not found")
    return {"session": data, "reviews": state.store.get_reviews(session_id)}


@router.put("/sessions/{session_id}/reviews")
def save_reviews(request: Request, session_id: str, body: ReviewsRequest) -> dict[str, Any]:
    state = _state(request)
    data = state.store.load_session(session_id)
    if data is None:
        raise HTTPException(404, "session not found")
    session = TutoringSession.model_validate(data)

    # Validate everything before saving anything.
    for review in body.reviews:
        count = len(session.gaps) if review.item_type == "gap" else len(session.quality_notes)
        if review.item_index >= count:
            raise HTTPException(422, f"session has no {review.item_type} {review.item_index}")
        if review.decision == Decision.OVERRIDE:
            if state.graph.get_concept(review.concept_id or "") is None:
                raise HTTPException(422, f"unknown concept {review.concept_id}")
            if review.misconception_id and not state.graph.has_misconception(
                review.concept_id or "", review.misconception_id
            ):
                raise HTTPException(
                    422, f"{review.misconception_id} is not a misconception of {review.concept_id}"
                )

    for review in body.reviews:
        state.store.save_review(
            session_id, review.item_type, review.item_index, review.model_dump(mode="json")
        )
    return {"saved": len(body.reviews), "reviews": state.store.get_reviews(session_id)}


@router.get("/learners")
def list_learners(request: Request) -> list[str]:
    return _state(request).store.list_students()


@router.get("/learners/{student_id}/events")
def learner_events(request: Request, student_id: str) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in _state(request).store.get_events(student_id)]


@router.get("/concepts")
def concepts(request: Request) -> dict[str, Any]:
    """The concept graph, so the dashboard can offer valid override choices."""
    return _state(request).graph.model_dump(mode="json")
