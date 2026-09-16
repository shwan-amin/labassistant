"""Structured diagnosis output.

Two separate kinds of feedback, kept apart on purpose:
* concept gaps: tied to the concept graph, used for questions, teaching material
  and the learner model;
* quality notes: general good-practice observations, never linked to concepts.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from labassistant.llm.base import Usage


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class QualityCategory(StrEnum):
    NAMING = "naming"
    DUPLICATION = "duplication"
    ERROR_HANDLING = "error_handling"
    READABILITY = "readability"
    STRUCTURE = "structure"
    TESTING = "testing"
    OTHER = "other"


class Evidence(BaseModel):
    """Where the problem shows. Lines are 1-based and always paired with a path."""

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    test_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_order(self) -> "Evidence":
        if self.end_line < self.start_line:
            raise ValueError("end_line is before start_line")
        return self


class ConceptGap(BaseModel):
    concept_id: str
    misconception_id: str | None = None
    confidence: Confidence
    evidence: list[Evidence] = Field(min_length=1)
    # MARKERS ONLY: never shown to students (decision recorded in CLAUDE.md). It can
    # describe the fix in words, which the leak check cannot reliably detect. No code.
    rationale: str = ""


class QualityNote(BaseModel):
    category: QualityCategory
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    explanation: str = Field(min_length=1)


class DiagnosisOutput(BaseModel):
    """Exactly what the model must return, as JSON."""

    concept_gaps: list[ConceptGap] = Field(default_factory=list)
    quality_notes: list[QualityNote] = Field(default_factory=list)


class Adjustment(BaseModel):
    """A change made to the model's output during validation or the leak check."""

    action: str  # "rejected_gap", "repaired_gap", "dropped_evidence", "leak_removed", ...
    detail: str


class ToolCallRecord(BaseModel):
    """INTERNAL: kept for logs and evaluation, never sent to students."""

    input: dict[str, Any]
    is_error: bool
    status: str | None = None  # RunResult status, when the tool ran
    probe_code: str | None = None


class DiagnosisOptions(BaseModel):
    """Switches for experiments. Defaults are the normal product behaviour."""

    use_tool: bool = True
    include_concept_graph: bool = True
    max_tool_calls: int = Field(default=6, ge=0)
    max_turns: int = Field(default=10, ge=1)


class DiagnosisResult(BaseModel):
    concept_gaps: list[ConceptGap]
    quality_notes: list[QualityNote]
    options: DiagnosisOptions
    model: str
    usage: Usage
    estimated_cost_usd: float | None  # None when no price is configured for the model
    turns: int
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    adjustments: list[Adjustment] = Field(default_factory=list)
    context_summary: dict[str, Any] = Field(default_factory=dict)
    retried_invalid_output: bool = False

    @property
    def leaks_removed(self) -> int:
        return sum(a.action == "leak_removed" for a in self.adjustments)
