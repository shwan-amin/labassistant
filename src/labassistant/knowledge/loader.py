"""Load and validate concept graphs from JSON files."""

import json
from pathlib import Path

from pydantic import ValidationError

from labassistant.knowledge.schema import ConceptGraph


class ConceptGraphError(ValueError):
    """Raised when a concept graph file is missing, malformed or invalid."""


def load_concept_graph(path: Path) -> ConceptGraph:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConceptGraphError(f"concept graph file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConceptGraphError(f"{path} is not valid JSON: {exc}") from exc

    try:
        return ConceptGraph.model_validate(raw)
    except ValidationError as exc:
        raise ConceptGraphError(f"{path} is not a valid concept graph:\n{exc}") from exc


def load_topic(topic: str, knowledge_dir: Path) -> ConceptGraph:
    """Load `<knowledge_dir>/<topic>.json`, e.g. load_topic("recursion", Path("knowledge"))."""
    return load_concept_graph(knowledge_dir / f"{topic}.json")
