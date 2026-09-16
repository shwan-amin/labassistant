"""Judge a student's reply: does it confirm or clear the suspected gap?"""

from pydantic import BaseModel, Field

from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.base import LLMClient, Usage
from labassistant.llm.structured import complete_json
from labassistant.tutoring import prompts
from labassistant.tutoring.models import GapState, Verdict
from labassistant.tutoring.questions import describe_gap

MAX_ANSWER_CHARS = 2_000


class AnswerEvaluation(BaseModel):
    verdict: Verdict
    rationale: str = Field(default="")


def evaluate_answer(
    client: LLMClient, graph: ConceptGraph, state: GapState, answer: str
) -> tuple[AnswerEvaluation, Usage]:
    """Raises StructuredOutputError if the model cannot give a valid verdict."""
    gap = describe_gap(state, graph)
    # The answer goes inside clear delimiters: it is data to judge, not instructions.
    user = (
        f"CONCEPT: {gap['concept']}\n"
        f"CONCEPT DESCRIPTION: {gap['concept_description']}\n"
        f"SUSPECTED MISCONCEPTION: {gap['suspected_misconception'] or 'not specified'}\n\n"
        f"CODE:\n{gap['evidence']}\n\n"
        f"QUESTION ASKED:\n{state.question}\n\n"
        f"<student_reply>\n{answer}\n</student_reply>"
    )
    return complete_json(
        client, system=prompts.ANSWER_SYSTEM, user=user, model=AnswerEvaluation, max_tokens=2_000
    )
