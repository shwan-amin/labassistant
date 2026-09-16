from pathlib import Path

import pytest

from labassistant.context import ProjectFile
from labassistant.diagnosis.models import DiagnosisOutput
from labassistant.diagnosis.validation import (
    InvalidOutputError,
    check_against_project,
    parse_output,
)
from labassistant.knowledge import load_topic

GRAPH = load_topic("recursion", Path(__file__).parent.parent / "knowledge")
FILES = [ProjectFile(path="metrics.py", content="line\n" * 30)]
TESTS = {"tests/test_metrics.py::test_depth"}


def gap(**overrides) -> dict:
    data = {
        "concept_id": "base_case",
        "misconception_id": "base_case_wrong_value",
        "confidence": "high",
        "evidence": [
            {
                "path": "metrics.py",
                "start_line": 22,
                "end_line": 24,
                "test_ids": ["tests/test_metrics.py::test_depth"],
            }
        ],
        "rationale": "The empty case is counted wrongly.",
    }
    data.update(overrides)
    return data


def check(*gaps: dict, notes: list[dict] | None = None):
    output = DiagnosisOutput.model_validate(
        {"concept_gaps": list(gaps), "quality_notes": notes or []}
    )
    return check_against_project(output, GRAPH, FILES, TESTS)


# --- parsing ---


def test_parse_plain_fenced_and_wrapped_json() -> None:
    body = '{"concept_gaps": [], "quality_notes": []}'
    for text in (body, f"```json\n{body}\n```", f"Here you go:\n{body}\nThanks"):
        assert parse_output(text) == DiagnosisOutput()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no json here", "no JSON object"),
        ('{"concept_gaps": [}', "invalid JSON"),
        ('{"concept_gaps": [{"concept_id": "base_case"}]}', "required shape"),
        ('{"concept_gaps": [], "quality_notes": [{"category": "vibes"}]}', "required shape"),
    ],
)
def test_parse_errors(text: str, message: str) -> None:
    with pytest.raises(InvalidOutputError, match=message):
        parse_output(text)


# --- checks against the graph and project ---


def test_valid_gap_is_kept_unchanged() -> None:
    output, adjustments = check(gap())
    assert len(output.concept_gaps) == 1
    assert adjustments == []


def test_unknown_concept_is_rejected() -> None:
    output, adjustments = check(gap(concept_id="pointers", misconception_id=None))
    assert output.concept_gaps == []
    assert adjustments[0].action == "rejected_gap"


def test_misconception_under_wrong_concept_is_moved() -> None:
    output, adjustments = check(gap(concept_id="call_stack"))
    assert output.concept_gaps[0].concept_id == "base_case"
    assert adjustments[0].action == "repaired_gap"


def test_unknown_misconception_is_removed() -> None:
    output, _ = check(gap(misconception_id="made_up"))
    assert output.concept_gaps[0].misconception_id is None
    assert output.concept_gaps[0].concept_id == "base_case"


def test_evidence_outside_the_project_is_dropped() -> None:
    evidence = [
        {"path": "metrics.py", "start_line": 29, "end_line": 31},  # file has 30 lines
        {"path": "ghost.py", "start_line": 1, "end_line": 1},
        {
            "path": "metrics.py",
            "start_line": 5,
            "end_line": 5,
            "test_ids": ["tests/nope.py::test_x"],
        },
    ]
    output, adjustments = check(gap(evidence=evidence))

    [kept] = output.concept_gaps[0].evidence
    assert (kept.start_line, kept.test_ids) == (5, [])
    assert [a.action for a in adjustments] == [
        "dropped_evidence",
        "dropped_evidence",
        "dropped_test_ids",
    ]


def test_gap_without_valid_evidence_is_rejected() -> None:
    output, adjustments = check(
        gap(evidence=[{"path": "ghost.py", "start_line": 1, "end_line": 1}])
    )
    assert output.concept_gaps == []
    assert adjustments[-1].action == "rejected_gap"


def test_quality_notes_with_bad_lines_are_rejected() -> None:
    notes = [
        {
            "category": "naming",
            "path": "metrics.py",
            "start_line": 3,
            "end_line": 3,
            "explanation": "Vague name.",
        },
        {
            "category": "naming",
            "path": "metrics.py",
            "start_line": 40,
            "end_line": 41,
            "explanation": "x",
        },
    ]
    output, adjustments = check(notes=notes)
    assert len(output.quality_notes) == 1
    assert adjustments[0].action == "rejected_note"
