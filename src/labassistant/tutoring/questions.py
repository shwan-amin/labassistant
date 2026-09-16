"""Generate one guiding question per gap, in a single LLM call."""

import json

from pydantic import BaseModel, Field

from labassistant.context.models import ProjectFile
from labassistant.diagnosis.leak_check import find_leaks
from labassistant.diagnosis.models import Adjustment
from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.base import LLMClient, Usage
from labassistant.llm.structured import StructuredOutputError, complete_json
from labassistant.runner.sandbox import PROBE_FILE_NAME
from labassistant.tutoring import prompts
from labassistant.tutoring.models import GapState

MAX_QUESTION_CHARS = 400
EXCERPT_CONTEXT_LINES = 2


class GeneratedQuestion(BaseModel):
    gap_index: int
    question: str = Field(min_length=1)


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]


def evidence_excerpt(state: GapState, files: list[ProjectFile]) -> str:
    """Numbered code around each evidence range, with a little context either side."""
    by_path = {f.path: f.lines for f in files}
    excerpts = []
    for evidence in state.gap.evidence:
        lines = by_path.get(evidence.path, [])
        start = max(1, evidence.start_line - EXCERPT_CONTEXT_LINES)
        end = min(len(lines), evidence.end_line + EXCERPT_CONTEXT_LINES)
        body = "\n".join(f"{n:>4} | {lines[n - 1]}" for n in range(start, end + 1))
        # Probe tests are private to the diagnosis agent: questions must not mention them.
        project_tests = [t for t in evidence.test_ids if not t.startswith(PROBE_FILE_NAME)]
        tests = f"\nfailing tests: {', '.join(project_tests)}" if project_tests else ""
        header = f"{evidence.path} (evidence lines {evidence.start_line}-{evidence.end_line}):"
        excerpts.append(f"{header}\n{body}{tests}")
    return "\n\n".join(excerpts)


def describe_gap(state: GapState, graph: ConceptGraph) -> dict:
    concept = graph.get_concept(state.gap.concept_id)
    misconception = next(
        (
            m
            for m in (concept.misconceptions if concept else [])
            if m.id == state.gap.misconception_id
        ),
        None,
    )
    return {
        "gap_index": state.index,
        "concept": concept.name if concept else state.gap.concept_id,
        "concept_description": concept.description if concept else "",
        "suspected_misconception": misconception.description if misconception else None,
        "evidence": state.evidence_excerpt,
    }


def generate_questions(
    client: LLMClient,
    graph: ConceptGraph,
    gaps: list[GapState],
    explanation: str | None,
) -> tuple[Usage, list[Adjustment]]:
    """Fill in `question` on each gap. Falls back to a template question when needed.

    Mutates the GapState objects. Returns (usage, adjustments).
    """
    if not gaps:
        return Usage(), []

    user = "GAPS:\n" + json.dumps([describe_gap(g, graph) for g in gaps], indent=1)
    if explanation and explanation.strip():
        user += f"\n\nSTUDENT'S EXPLANATION OF THEIR CODE:\n{explanation.strip()}"

    adjustments: list[Adjustment] = []
    usage = Usage()
    generated: dict[int, str] = {}
    try:
        output, usage = complete_json(
            client,
            system=prompts.QUESTION_SYSTEM,
            user=user,
            model=GeneratedQuestions,
            max_tokens=4_000,
        )
        generated = {q.gap_index: q.question.strip() for q in output.questions}
    except StructuredOutputError as exc:
        adjustments.append(Adjustment(action="question_generation_failed", detail=str(exc)))

    for state in gaps:
        question = generated.get(state.index)
        problem = _question_problem(question)
        if problem is None:
            state.question, state.question_source = question, "llm"
            continue
        adjustments.append(
            Adjustment(action="question_replaced", detail=f"gap {state.index}: {problem}")
        )
        first = state.gap.evidence[0]
        state.question = prompts.template_question(first.path, first.start_line, first.end_line)
        state.question_source = "template"
    return usage, adjustments


def _question_problem(question: str | None) -> str | None:
    if not question:
        return "no question generated"
    if len(question) > MAX_QUESTION_CHARS:
        return "question too long"
    if "?" not in question:
        return "not a question"
    if leaks := find_leaks(question):
        # Recorded as a leak so the evaluation counts it with the diagnosis leaks.
        return f"leak_removed: {leaks[0].reason}: {leaks[0].snippet}"
    return None
