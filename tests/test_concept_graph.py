import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from labassistant.knowledge import ConceptGraph, ConceptGraphError, load_concept_graph, load_topic

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


def concept(id_: str, prerequisites: list[str] | None = None, misconceptions=None) -> dict:
    """Build a minimal valid concept dict for tests."""
    return {
        "id": id_,
        "name": id_.replace("_", " "),
        "description": f"about {id_}",
        "prerequisites": prerequisites or [],
        "misconceptions": misconceptions or [],
    }


def misconception(id_: str) -> dict:
    return {"id": id_, "description": f"believes {id_}", "symptoms": ["a symptom"]}


def graph(*concepts: dict) -> dict:
    return {"topic": "test_topic", "concepts": list(concepts)}


# --- the real recursion graph ---


def test_recursion_graph_loads_and_meets_size_requirements() -> None:
    recursion = load_topic("recursion", KNOWLEDGE_DIR)

    assert recursion.topic == "recursion"
    assert 6 <= len(recursion.concepts) <= 8
    for c in recursion.concepts:
        assert 2 <= len(c.misconceptions) <= 3, c.id


def test_recursion_graph_topological_order_respects_prerequisites() -> None:
    recursion = load_topic("recursion", KNOWLEDGE_DIR)
    order = recursion.topological_order()

    assert sorted(order) == sorted(recursion.concept_ids)
    for c in recursion.concepts:
        for prereq in c.prerequisites:
            assert order.index(prereq) < order.index(c.id)


# --- lookups ---


def test_has_misconception_checks_ownership() -> None:
    g = ConceptGraph.model_validate(
        graph(concept("a", misconceptions=[misconception("a_wrong")]), concept("b"))
    )

    assert g.has_misconception("a", "a_wrong")
    assert not g.has_misconception("b", "a_wrong")  # exists, but belongs to another concept
    assert not g.has_misconception("missing", "a_wrong")
    assert g.get_concept("missing") is None


# --- invalid graphs ---


@pytest.mark.parametrize(
    ("data", "expected_message"),
    [
        (graph(concept("a"), concept("a")), "duplicate concept ids: ['a']"),
        (
            graph(
                concept("a", misconceptions=[misconception("m")]),
                concept("b", misconceptions=[misconception("m")]),
            ),
            "duplicate misconception ids: ['m']",
        ),
        (graph(concept("a", ["ghost"])), "unknown prerequisite 'ghost'"),
        (graph(concept("a", ["a"])), "lists itself as a prerequisite"),
        (
            graph(concept("a", ["b"]), concept("b", ["a"])),
            "prerequisite cycle involving: ['a', 'b']",
        ),
        (
            graph(
                concept("root"),
                concept("a", ["root", "c"]),
                concept("b", ["a"]),
                concept("c", ["b"]),
            ),
            "prerequisite cycle involving: ['a', 'b', 'c']",
        ),
        (graph(concept("Base Case")), "String should match pattern"),
        (graph(), "at least 1 item"),
    ],
    ids=[
        "duplicate-concept",
        "duplicate-misconception",
        "unknown-prerequisite",
        "self-prerequisite",
        "two-node-cycle",
        "three-node-cycle",
        "bad-id-format",
        "no-concepts",
    ],
)
def test_invalid_graphs_are_rejected(data: dict, expected_message: str) -> None:
    with pytest.raises(ValidationError, match=expected_message.replace("[", r"\[")):
        ConceptGraph.model_validate(data)


def test_misconception_needs_symptoms() -> None:
    bad = {"id": "m", "description": "d", "symptoms": []}
    with pytest.raises(ValidationError, match="symptoms"):
        ConceptGraph.model_validate(graph(concept("a", misconceptions=[bad])))


def test_all_reference_problems_reported_together() -> None:
    data = graph(concept("a", ["ghost"]), concept("a"))
    with pytest.raises(ValidationError) as exc_info:
        ConceptGraph.model_validate(data)
    message = str(exc_info.value)
    assert "duplicate concept ids" in message
    assert "unknown prerequisite" in message


# --- loader errors ---


def test_loader_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConceptGraphError, match="not found"):
        load_concept_graph(tmp_path / "nope.json")


def test_loader_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConceptGraphError, match="not valid JSON"):
        load_concept_graph(path)


def test_loader_wraps_validation_errors_with_file_name(tmp_path: Path) -> None:
    path = tmp_path / "cyclic.json"
    path.write_text(json.dumps(graph(concept("a", ["b"]), concept("b", ["a"]))), encoding="utf-8")
    with pytest.raises(ConceptGraphError, match="cyclic.json") as exc_info:
        load_concept_graph(path)
    assert "cycle" in str(exc_info.value)
