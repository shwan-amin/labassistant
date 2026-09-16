"""Pydantic models for the concept graph.

The graph is the backbone of Lab Assistant: diagnoses, questions, teaching
material and the learner model all refer to the IDs defined here.
"""

from collections import Counter

from pydantic import BaseModel, Field, model_validator

# Lowercase snake_case, e.g. "base_case". Stable, readable IDs matter because
# they appear in prompts, LLM output, tag files and the database.
ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class Misconception(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    description: str = Field(min_length=1)
    # Observable signs in code or explanations, given to the LLM as hints.
    symptoms: list[str] = Field(min_length=1)


class Concept(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    # IDs of concepts a student should understand before this one.
    prerequisites: list[str] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)


class ConceptGraph(BaseModel):
    topic: str = Field(pattern=ID_PATTERN)
    description: str = ""
    concepts: list[Concept] = Field(min_length=1)

    @model_validator(mode="after")
    def check_graph_structure(self) -> "ConceptGraph":
        # Collect every problem before raising, so a hand-edited file can be
        # fixed in one pass instead of one error at a time.
        problems = _find_structural_problems(self.concepts)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # --- lookups used by the rest of the system ---

    @property
    def concept_ids(self) -> set[str]:
        return {concept.id for concept in self.concepts}

    def get_concept(self, concept_id: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == concept_id), None)

    def has_misconception(self, concept_id: str, misconception_id: str) -> bool:
        """True if the misconception exists *and* belongs to that concept."""
        concept = self.get_concept(concept_id)
        return concept is not None and any(m.id == misconception_id for m in concept.misconceptions)

    def topological_order(self) -> list[str]:
        """Concept IDs ordered so prerequisites come before the concepts that need them."""
        order, _ = _kahn_sort(self.concepts)
        return order


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(id_ for id_, count in Counter(ids).items() if count > 1)


def _find_structural_problems(concepts: list[Concept]) -> list[str]:
    problems: list[str] = []

    concept_ids = [c.id for c in concepts]
    if dupes := _duplicates(concept_ids):
        problems.append(f"duplicate concept ids: {dupes}")

    # Misconception IDs are unique across the whole graph, not just per concept,
    # so a misconception ID on its own is unambiguous in labels and logs.
    misconception_ids = [m.id for c in concepts for m in c.misconceptions]
    if dupes := _duplicates(misconception_ids):
        problems.append(f"duplicate misconception ids: {dupes}")

    known = set(concept_ids)
    for concept in concepts:
        for prereq in concept.prerequisites:
            if prereq == concept.id:
                problems.append(f"concept '{concept.id}' lists itself as a prerequisite")
            elif prereq not in known:
                problems.append(f"concept '{concept.id}' has unknown prerequisite '{prereq}'")

    # Only look for cycles once references are valid; otherwise the cycle
    # report would be confusing noise on top of the real error.
    if not problems:
        _, stuck = _kahn_sort(concepts)
        if stuck:
            problems.append(f"prerequisite cycle involving: {sorted(stuck)}")

    return problems


def _kahn_sort(concepts: list[Concept]) -> tuple[list[str], set[str]]:
    """Kahn's algorithm for topological sorting.

    Repeatedly take a concept whose prerequisites are all already placed. If we
    get stuck with concepts left over, those concepts are in (or depend on) a cycle.
    Returns (ordered ids, ids that could not be placed).
    """
    remaining_prereqs = {c.id: set(c.prerequisites) for c in concepts}
    order: list[str] = []
    ready = [c.id for c in concepts if not c.prerequisites]

    while ready:
        current = ready.pop(0)
        order.append(current)
        for concept_id, prereqs in remaining_prereqs.items():
            if current in prereqs:
                prereqs.remove(current)
                if not prereqs:
                    ready.append(concept_id)

    stuck = set(remaining_prereqs) - set(order)
    return order, stuck
