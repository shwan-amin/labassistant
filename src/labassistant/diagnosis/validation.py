"""Parse and check the model's diagnosis against the concept graph and the project."""

from labassistant.context.models import ProjectFile
from labassistant.diagnosis.models import (
    Adjustment,
    ConceptGap,
    DiagnosisOutput,
    Evidence,
)
from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.structured import InvalidOutputError, parse_json_model

__all__ = ["InvalidOutputError", "check_against_project", "parse_output"]


def parse_output(text: str) -> DiagnosisOutput:
    """Parse the model's reply into the diagnosis shape (raises InvalidOutputError)."""
    return parse_json_model(text, DiagnosisOutput)


def check_against_project(
    output: DiagnosisOutput,
    graph: ConceptGraph,
    files: list[ProjectFile],
    known_test_ids: set[str],
) -> tuple[DiagnosisOutput, list[Adjustment]]:
    """Reject or repair anything that refers to concepts, files, lines or tests that don't exist."""
    line_counts = {f.path: len(f.lines) for f in files}
    adjustments: list[Adjustment] = []

    gaps = []
    for gap in output.concept_gaps:
        checked = _check_gap(gap, graph, line_counts, known_test_ids, adjustments)
        if checked is not None:
            gaps.append(checked)

    notes = []
    for note in output.quality_notes:
        if _lines_exist(note.path, note.start_line, note.end_line, line_counts):
            notes.append(note)
        else:
            adjustments.append(
                Adjustment(
                    action="rejected_note",
                    detail=f"{note.path} lines {note.start_line}-{note.end_line} do not exist",
                )
            )
    return DiagnosisOutput(concept_gaps=gaps, quality_notes=notes), adjustments


def _check_gap(
    gap: ConceptGap,
    graph: ConceptGraph,
    line_counts: dict[str, int],
    known_test_ids: set[str],
    adjustments: list[Adjustment],
) -> ConceptGap | None:
    concept_id, misconception_id = gap.concept_id, gap.misconception_id

    if misconception_id is not None and not graph.has_misconception(concept_id, misconception_id):
        owner = _misconception_owner(graph, misconception_id)
        if owner is not None:
            # A real misconception under the wrong concept: trust the more specific id.
            adjustments.append(
                Adjustment(
                    action="repaired_gap",
                    detail=f"moved {misconception_id} from {concept_id} to its concept {owner}",
                )
            )
            concept_id = owner
        else:
            adjustments.append(
                Adjustment(
                    action="repaired_gap",
                    detail=f"removed unknown misconception {misconception_id}",
                )
            )
            misconception_id = None

    if graph.get_concept(concept_id) is None:
        adjustments.append(
            Adjustment(action="rejected_gap", detail=f"unknown concept {concept_id}")
        )
        return None

    evidence = []
    for item in gap.evidence:
        if not _lines_exist(item.path, item.start_line, item.end_line, line_counts):
            adjustments.append(
                Adjustment(
                    action="dropped_evidence",
                    detail=f"{item.path} lines {item.start_line}-{item.end_line} do not exist",
                )
            )
            continue
        unknown_tests = [t for t in item.test_ids if t not in known_test_ids]
        if unknown_tests:
            adjustments.append(
                Adjustment(action="dropped_test_ids", detail=f"unknown test ids {unknown_tests}")
            )
        evidence.append(
            Evidence(
                path=item.path,
                start_line=item.start_line,
                end_line=item.end_line,
                test_ids=[t for t in item.test_ids if t in known_test_ids],
            )
        )

    if not evidence:
        adjustments.append(
            Adjustment(action="rejected_gap", detail=f"{concept_id}: no valid evidence left")
        )
        return None

    return gap.model_copy(
        update={
            "concept_id": concept_id,
            "misconception_id": misconception_id,
            "evidence": evidence,
        }
    )


def _misconception_owner(graph: ConceptGraph, misconception_id: str) -> str | None:
    for concept in graph.concepts:
        if any(m.id == misconception_id for m in concept.misconceptions):
            return concept.id
    return None


def _lines_exist(path: str, start: int, end: int, line_counts: dict[str, int]) -> bool:
    return path in line_counts and 1 <= start <= end <= line_counts[path]
