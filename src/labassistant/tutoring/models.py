"""Session state for Socratic questioning.

Two views of the same session:
* TutoringSession: everything, for storage, markers and evaluation.
* StudentSessionView: only what a student may see (no rationales, no probe code,
  no misconception descriptions that could hint at the fix).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from labassistant.context.models import LineRange
from labassistant.diagnosis.models import Adjustment, ConceptGap, DiagnosisResult, QualityNote
from labassistant.knowledge.schema import ConceptGraph
from labassistant.learner.store import MasteryUpdate
from labassistant.llm.base import Usage
from labassistant.runner.sandbox import PROBE_FILE_NAME


class GapStatus(StrEnum):
    SUSPECTED = "suspected"  # waiting for the student's answer
    CONFIRMED = "confirmed"  # the answer showed the misconception
    CLEARED = "cleared"  # the answer showed understanding
    SHOWN = "shown"  # questioning was skipped; feedback shown directly


class Verdict(StrEnum):
    CONFIRMED = "confirmed"
    CLEARED = "cleared"


class GapState(BaseModel):
    index: int
    gap: ConceptGap
    status: GapStatus
    # Numbered code around the evidence, reused when judging the answer. Internal.
    evidence_excerpt: str = ""
    question: str | None = None
    question_source: Literal["llm", "template"] | None = None
    answer: str | None = None
    # MARKERS ONLY, like the gap rationale.
    evaluation_rationale: str | None = None
    mastery_update: MasteryUpdate | None = None


class TutoringSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    student_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    selected_path: str
    selection: LineRange
    explanation: str | None = None
    skip_questioning: bool = False
    diagnosis: DiagnosisResult
    gaps: list[GapState]
    question_usage: Usage = Field(default_factory=Usage)
    answer_usage: Usage = Field(default_factory=Usage)
    adjustments: list[Adjustment] = Field(default_factory=list)

    @property
    def quality_notes(self) -> list[QualityNote]:
        return self.diagnosis.quality_notes

    @property
    def total_usage(self) -> Usage:
        return self.diagnosis.usage + self.question_usage + self.answer_usage

    def next_gap(self) -> GapState | None:
        """The next gap waiting for an answer, one at a time, in diagnosis order."""
        return next((g for g in self.gaps if g.status == GapStatus.SUSPECTED), None)

    @property
    def is_complete(self) -> bool:
        return self.next_gap() is None

    def student_view(self, graph: ConceptGraph) -> "StudentSessionView":
        return StudentSessionView(
            session_id=self.id,
            selected_path=self.selected_path,
            selection=self.selection,
            complete=self.is_complete,
            gaps=[_student_gap(state, graph) for state in self.gaps],
            quality_notes=[
                StudentQualityNote(
                    category=note.category.value,
                    path=note.path,
                    start_line=note.start_line,
                    end_line=note.end_line,
                    explanation=note.explanation,
                )
                for note in self.quality_notes
            ],
        )


class StudentEvidence(BaseModel):
    path: str
    start_line: int
    end_line: int
    test_ids: list[str]


class StudentGapView(BaseModel):
    index: int
    concept_id: str
    concept_name: str
    status: GapStatus
    evidence: list[StudentEvidence]
    question: str | None


class StudentQualityNote(BaseModel):
    category: str
    path: str
    start_line: int
    end_line: int
    explanation: str


class StudentSessionView(BaseModel):
    session_id: str
    selected_path: str
    selection: LineRange
    complete: bool
    gaps: list[StudentGapView]
    quality_notes: list[StudentQualityNote]


def _student_gap(state: GapState, graph: ConceptGraph) -> StudentGapView:
    concept = graph.get_concept(state.gap.concept_id)
    return StudentGapView(
        index=state.index,
        concept_id=state.gap.concept_id,
        concept_name=concept.name if concept else state.gap.concept_id,
        status=state.status,
        evidence=[
            StudentEvidence(
                path=e.path,
                start_line=e.start_line,
                end_line=e.end_line,
                # Probe tests are private to the agent, so their ids are hidden too.
                test_ids=[t for t in e.test_ids if not t.startswith(PROBE_FILE_NAME)],
            )
            for e in state.gap.evidence
        ],
        question=state.question,
    )
