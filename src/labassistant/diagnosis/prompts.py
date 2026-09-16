"""Prompts for the diagnosis agent, kept as constants so experiments can compare them.

Layout, for prompt caching:
    system  = instructions + concept graph + stable project context (repo map, spec)
    user    = changing code context + student's explanation + the request
Anything that changes between checks must stay out of the system prompt.
"""

import json

from labassistant.context.builder import BuiltContext
from labassistant.knowledge.schema import ConceptGraph

INSTRUCTIONS = """\
You are Lab Assistant, a tutor that assesses a student's *understanding* of core \
computing concepts from code they highlight in their lab work. You do not mark the work.

Your job: diagnose suspected concept gaps or misconceptions shown by the selected code, \
and separately note general code-quality issues.

ACADEMIC INTEGRITY (hard rules):
- Never write a solution, corrected code, or code the student could paste in.
- Do not include code blocks, code statements or rewritten lines anywhere in your output.
- You may refer to file paths, line numbers, test ids and names of functions or variables.
- Explain concepts in general terms only.
- Never state the fix in words either (for example, which value to use instead, or \
what to add or remove). Describe the misunderstanding, not the change to make.

HOW TO WORK:
- Focus on the selected code; use the rest of the context to understand it.
- Base every concept gap on evidence: file and line numbers, and failing test ids if relevant.
- Evidence line ranges must be as narrow as possible: point at the exact line(s) that show \
the problem, not the whole function.
- Only report a gap if the code gives real evidence of it. Correct code should get no gaps.
- Use confidence "high" only when tests or unambiguous code confirm it.
- Quality notes are about general good practice (naming, duplication, error handling, \
readability, structure, testing). They are not concept gaps. Keep them few and useful.
"""

TOOL_INSTRUCTIONS = """\
TOOLS:
- You can call run_tests to run the project's existing tests, or to run a small probe \
test you write to check a specific hypothesis. Probe tests are private to you.
- Use the tool when running code would confirm or rule out a suspected gap. Do not call \
it more than needed.
"""

NO_TOOL_INSTRUCTIONS = """\
TOOLS: none are available. Reason from the code alone.
"""

OUTPUT_INSTRUCTIONS = """\
OUTPUT: when finished, reply with only a JSON object, no other text, in this shape:
{
  "concept_gaps": [
    {
      "concept_id": "<id from the concept list>",
      "misconception_id": "<misconception id from that concept, or null>",
      "confidence": "low" | "medium" | "high",
      "evidence": [
        {"path": "<file>", "start_line": <int>, "end_line": <int>, "test_ids": ["<test id>"]}
      ],
      "rationale": "<one or two plain sentences on the misunderstanding; no code, no fix>"
    }
  ],
  "quality_notes": [
    {
      "category": "naming" | "duplication" | "error_handling" | "readability" | \
"structure" | "testing" | "other",
      "path": "<file>", "start_line": <int>, "end_line": <int>,
      "explanation": "<one or two plain sentences, no code>"
    }
  ]
}
Use empty lists when there is nothing to report.
"""

REQUEST = "Diagnose the selected code. Reply with the JSON object only."

RETRY_TEMPLATE = """\
Your previous reply could not be used: {error}
Reply again with only the corrected JSON object, following the required shape. No code."""

TOOL_LIMIT_MESSAGE = (
    "Tool call limit reached. Do not call tools again; give your final JSON answer."
)


def render_concept_graph(graph: ConceptGraph) -> str:
    """Full graph: concepts, prerequisites and misconceptions with symptoms."""
    concepts = [
        {
            "id": concept.id,
            "name": concept.name,
            "description": concept.description,
            "prerequisites": concept.prerequisites,
            "misconceptions": [
                {"id": m.id, "description": m.description, "symptoms": m.symptoms}
                for m in concept.misconceptions
            ],
        }
        for concept in graph.concepts
    ]
    return json.dumps({"topic": graph.topic, "concepts": concepts}, indent=1)


def render_concept_list(graph: ConceptGraph) -> str:
    """Ablation for the 'without concept graph' condition: bare ids and names only.

    Gaps must still use valid ids so results can be scored, but the model gets no
    descriptions, prerequisites or misconception catalogue.
    """
    return "\n".join(f"- {concept.id}: {concept.name}" for concept in graph.concepts)


def build_system_prompt(
    graph: ConceptGraph, context: BuiltContext, *, use_tool: bool, include_concept_graph: bool
) -> str:
    if include_concept_graph:
        concepts = f"CONCEPT GRAPH (topic: {graph.topic}):\n{render_concept_graph(graph)}"
    else:
        concepts = (
            f"CONCEPTS (topic: {graph.topic}). Use these ids; set misconception_id to null:\n"
            f"{render_concept_list(graph)}"
        )
    sections = [
        INSTRUCTIONS,
        TOOL_INSTRUCTIONS if use_tool else NO_TOOL_INSTRUCTIONS,
        OUTPUT_INSTRUCTIONS,
        concepts,
    ]
    stable = context.stable_text()
    if stable:
        sections.append(f"PROJECT OVERVIEW:\n{stable}")
    return "\n\n".join(sections)


def build_user_message(context: BuiltContext, explanation: str | None) -> str:
    sections = [f"CODE CONTEXT (selection: {context.selected_path} {context.selection}):"]
    sections.append(context.dynamic_text())
    if explanation and explanation.strip():
        sections.append(f"STUDENT'S EXPLANATION OF THEIR CODE:\n{explanation.strip()}")
    sections.append(REQUEST)
    return "\n\n".join(sections)
