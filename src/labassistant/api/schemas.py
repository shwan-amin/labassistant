"""Request and response models for the HTTP API.

Every response is built from student-safe views: no gap rationales, answer
evaluation rationales, misconception ids or probe tests ever leave the backend
through these endpoints.
"""

from pydantic import BaseModel, Field

from labassistant.context.models import LineRange, ProjectFile
from labassistant.learner.mastery import MasteryState
from labassistant.tutoring.models import GapStatus, StudentSessionView

ID_PATTERN = r"^[A-Za-z0-9_.@-]{1,64}$"


class CheckRequest(BaseModel):
    files: list[ProjectFile] = Field(max_length=5_000)
    selected_path: str
    selection: LineRange
    explanation: str | None = Field(default=None, max_length=2_000)
    student_id: str | None = Field(default=None, pattern=ID_PATTERN)
    # None means "use the server's SKIP_QUESTIONING setting".
    skip_questioning: bool | None = None


class QuestionView(BaseModel):
    gap_index: int
    concept_name: str
    question: str


class CheckResponse(BaseModel):
    session: StudentSessionView
    next_question: QuestionView | None


class AnswerRequest(BaseModel):
    gap_index: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=2_000)


class MasteryChangeView(BaseModel):
    concept_id: str
    old_state: MasteryState
    new_state: MasteryState


class MaterialView(BaseModel):
    kind: str  # "lecture" or "slide"
    source_title: str
    note: str
    url: str | None
    start_seconds: float | None = None
    end_seconds: float | None = None
    slide_number: int | None = None
    thumbnail_url: str | None = None  # served by GET /materials/thumbnails/...
    attribution: str


class AnswerResponse(BaseModel):
    gap_index: int
    status: GapStatus
    mastery_change: MasteryChangeView | None
    # Teaching material, included when the answer confirmed the gap.
    materials: list[MaterialView]
    next_question: QuestionView | None
    complete: bool


class ConceptNode(BaseModel):
    id: str
    name: str
    description: str
    state: MasteryState
    prerequisites: list[str]


class ConceptEdge(BaseModel):
    source: str  # prerequisite concept
    target: str  # concept that depends on it


class ConceptMapResponse(BaseModel):
    student_id: str
    topic: str
    nodes: list[ConceptNode]
    edges: list[ConceptEdge]


class ErrorResponse(BaseModel):
    detail: str
