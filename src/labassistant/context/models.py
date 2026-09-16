"""Input models for building LLM context from a student's project."""

from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator


class ContextError(ValueError):
    """Raised when a request cannot be turned into context (e.g. selection out of range)."""


class ContextMode(StrEnum):
    """How much of the project the diagnosis agent sees. Compared in the evaluation."""

    SELECTION_ONLY = "selection_only"  # selection + enclosing function
    FILE = "file"  # ... + the rest of the selected file
    FULL = "full"  # ... + directly used code, repo map, spec and other files


class LineRange(BaseModel):
    """An inclusive, 1-based range of lines, e.g. start=3, end=5 covers lines 3, 4 and 5."""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def check_order(self) -> "LineRange":
        if self.end < self.start:
            raise ValueError(f"line range end ({self.end}) is before start ({self.start})")
        return self

    def contains(self, other: "LineRange") -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: "LineRange") -> bool:
        return self.start <= other.end and other.start <= self.end

    def __str__(self) -> str:
        return f"lines {self.start}-{self.end}" if self.end != self.start else f"line {self.start}"


def normalise_path(path: str) -> str:
    """Project-relative POSIX path, e.g. "./src\\main.py" -> "src/main.py"."""
    cleaned = path.replace("\\", "/").strip()
    parts = [part for part in PurePosixPath(cleaned).parts if part not in ("", ".", "/")]
    if not parts or ".." in parts:
        raise ValueError(f"invalid project path: {path!r}")
    return "/".join(parts)


class ProjectFile(BaseModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def clean_path(cls, value: str) -> str:
        return normalise_path(value)

    @property
    def lines(self) -> list[str]:
        return self.content.splitlines()

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")


class ContextRequest(BaseModel):
    files: list[ProjectFile]
    selected_path: str
    selection: LineRange
    explanation: str | None = None

    @field_validator("selected_path")
    @classmethod
    def clean_selected_path(cls, value: str) -> str:
        return normalise_path(value)
