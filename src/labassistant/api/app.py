"""The FastAPI application. Interfaces (VS Code extension, dashboard) only talk to this.

Endpoints are plain `def` functions: FastAPI runs them in a thread pool, which suits
the blocking work they do (LLM calls, sandboxed test runs, SQLite).
"""

import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from google.genai import errors as genai_errors

from labassistant.api.marker import router as marker_router
from labassistant.api.schemas import (
    AnswerRequest,
    AnswerResponse,
    CheckRequest,
    CheckResponse,
    ConceptEdge,
    ConceptMapResponse,
    ConceptNode,
    ErrorResponse,
    MasteryChangeView,
    MaterialView,
    QuestionView,
)
from labassistant.api.state import AppState
from labassistant.config import Settings, get_settings
from labassistant.context.models import ContextError, ContextRequest
from labassistant.diagnosis.agent import DiagnosisError
from labassistant.llm.base import LLMClient, MissingAPIKeyError
from labassistant.llm.gemini_client import DailyQuotaExceededError
from labassistant.llm.structured import StructuredOutputError
from labassistant.materials.retrieval import retrieve
from labassistant.tutoring.models import GapStatus, TutoringSession
from labassistant.tutoring.service import TutoringError

SAFE_ID = re.compile(r"^[a-z0-9_]{1,64}$")

ERRORS = {
    400: {"model": ErrorResponse, "description": "Invalid request"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Not allowed in the current session state"},
    413: {"model": ErrorResponse, "description": "Request too large"},
    422: {"model": ErrorResponse, "description": "Selection or project cannot be checked"},
    502: {"model": ErrorResponse, "description": "The LLM gave an unusable answer"},
    503: {"model": ErrorResponse, "description": "The LLM service is unavailable (key or quota)"},
}


def create_app(settings: Settings | None = None, client: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    state = AppState(settings, client)
    app = FastAPI(
        title="Lab Assistant API",
        version="0.1.0",
        description=(
            "Checks a student's understanding of highlighted code: diagnosis, Socratic "
            "questions, teaching material and a per-concept learner model. Local use only."
        ),
    )
    app.state.lab = state

    # Reject requests addressed to any other host name (defence against DNS rebinding
    # from a web page), in addition to binding to 127.0.0.1 when run.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api_allowed_hosts)

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            length = request.headers.get("content-length")
            if length is None:
                return JSONResponse({"detail": "Content-Length header required"}, status_code=411)
            if int(length) > settings.max_request_bytes:
                return JSONResponse(
                    {"detail": f"request is larger than {settings.max_request_bytes} bytes"},
                    status_code=413,
                )
        return await call_next(request)

    _add_error_handlers(app)
    app.include_router(marker_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "provider": str(settings.llm_provider),
            "model": settings.model_name,
        }

    @app.post("/checks", response_model=CheckResponse, responses=ERRORS, tags=["checks"])
    def start_check(body: CheckRequest) -> CheckResponse:
        """Diagnose the selected code and return the first Socratic question."""
        request = ContextRequest(
            files=body.files,
            selected_path=body.selected_path,
            selection=body.selection,
            explanation=body.explanation,
        )
        skip = settings.skip_questioning if body.skip_questioning is None else body.skip_questioning
        session = state.tutor().start(
            body.student_id or settings.student_id, request, skip_questioning=skip
        )
        return CheckResponse(
            session=session.student_view(state.graph), next_question=_next_question(session, state)
        )

    @app.get(
        "/checks/{session_id}", response_model=CheckResponse, responses=ERRORS, tags=["checks"]
    )
    def get_check(session_id: str) -> CheckResponse:
        session = _load_session(state, session_id)
        return CheckResponse(
            session=session.student_view(state.graph), next_question=_next_question(session, state)
        )

    @app.post(
        "/checks/{session_id}/answers",
        response_model=AnswerResponse,
        responses=ERRORS,
        tags=["checks"],
    )
    def submit_answer(session_id: str, body: AnswerRequest) -> AnswerResponse:
        """Judge the student's answer; confirmed gaps come back with teaching material."""
        session = _load_session(state, session_id)
        gap = state.tutor().answer(session, body.gap_index, body.answer)
        change = gap.mastery_update
        return AnswerResponse(
            gap_index=gap.index,
            status=gap.status,
            mastery_change=MasteryChangeView(
                concept_id=change.concept_id, old_state=change.old_state, new_state=change.new_state
            )
            if change
            else None,
            materials=_materials(state, gap.gap.concept_id)
            if gap.status == GapStatus.CONFIRMED
            else [],
            next_question=_next_question(session, state),
            complete=session.is_complete,
        )

    @app.get(
        "/checks/{session_id}/gaps/{gap_index}/materials",
        response_model=list[MaterialView],
        responses=ERRORS,
        tags=["materials"],
    )
    def gap_materials(session_id: str, gap_index: int) -> list[MaterialView]:
        """Teaching material for a gap that was confirmed (or shown when questioning is skipped)."""
        session = _load_session(state, session_id)
        gap = next((g for g in session.gaps if g.index == gap_index), None)
        if gap is None:
            raise HTTPException(404, f"session has no gap {gap_index}")
        if gap.status not in (GapStatus.CONFIRMED, GapStatus.SHOWN):
            raise HTTPException(409, "materials are available once the gap is confirmed")
        return _materials(state, gap.gap.concept_id)

    @app.get(
        "/materials/thumbnails/{source_id}/{slide_number}", tags=["materials"], responses=ERRORS
    )
    def slide_thumbnail(source_id: str, slide_number: int) -> FileResponse:
        # Strict id check: the path is built from these, so nothing like "../" gets through.
        if not SAFE_ID.match(source_id) or not 1 <= slide_number <= 9_999:
            raise HTTPException(404, "thumbnail not found")
        path = (
            settings.processed_materials_dir
            / "thumbnails"
            / source_id
            / f"slide-{slide_number:03d}.png"
        )
        if not path.is_file():
            raise HTTPException(404, "thumbnail not found")
        return FileResponse(path, media_type="image/png")

    @app.get(
        "/learners/{student_id}/mastery",
        response_model=ConceptMapResponse,
        responses=ERRORS,
        tags=["learners"],
    )
    def concept_map(student_id: str) -> ConceptMapResponse:
        """Mastery per concept, with prerequisite edges for drawing the concept map."""
        mastery = state.store.get_mastery(student_id)
        return ConceptMapResponse(
            student_id=student_id,
            topic=state.graph.topic,
            nodes=[
                ConceptNode(
                    id=c.id,
                    name=c.name,
                    description=c.description,
                    state=mastery[c.id].state,
                    prerequisites=c.prerequisites,
                )
                for c in state.graph.concepts
            ],
            edges=[
                ConceptEdge(source=p, target=c.id)
                for c in state.graph.concepts
                for p in c.prerequisites
            ],
        )

    return app


def _load_session(state: AppState, session_id: str) -> TutoringSession:
    session = state.tutor().load(session_id) if len(session_id) <= 64 else None
    if session is None:
        raise HTTPException(404, "check not found")
    return session


def _next_question(session: TutoringSession, state: AppState) -> QuestionView | None:
    gap = session.next_gap()
    if gap is None or gap.question is None:
        return None
    concept = state.graph.get_concept(gap.gap.concept_id)
    return QuestionView(
        gap_index=gap.index,
        concept_name=concept.name if concept else gap.gap.concept_id,
        question=gap.question,
    )


def _materials(state: AppState, concept_id: str) -> list[MaterialView]:
    links = retrieve(
        concept_id,
        state.tag_files,
        state.graph,
        thumbnail_root=state.settings.processed_materials_dir / "thumbnails",
    )
    return [
        MaterialView(
            kind=link.kind,
            source_title=link.source_title,
            note=link.note,
            url=link.url,
            start_seconds=link.start_seconds,
            end_seconds=link.end_seconds,
            slide_number=link.slide_number,
            thumbnail_url=f"/materials/thumbnails/{link.source_id}/{link.slide_number}"
            if link.thumbnail_path
            else None,
            attribution=link.attribution,
        )
        for link in links
    ]


def _add_error_handlers(app: FastAPI) -> None:
    """Map domain errors to HTTP status codes with a readable `detail` message."""

    def handler(status: int, prefix: str = ""):
        async def handle(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": f"{prefix}{exc}"}, status_code=status)

        return handle

    app.add_exception_handler(ContextError, handler(422))
    app.add_exception_handler(TutoringError, handler(409))
    app.add_exception_handler(DiagnosisError, handler(502, "diagnosis failed: "))
    app.add_exception_handler(StructuredOutputError, handler(502, "LLM output unusable: "))
    app.add_exception_handler(MissingAPIKeyError, handler(503))
    app.add_exception_handler(DailyQuotaExceededError, handler(503))
    app.add_exception_handler(genai_errors.APIError, handler(503, "LLM service error: "))
