"""Read, write and merge the reviewable tag files in materials/."""

import json
from pathlib import Path

from labassistant.knowledge.schema import ConceptGraph
from labassistant.materials.models import ChunkTag, SlideTag, TagFile


def load_tag_file(path: Path) -> TagFile:
    return TagFile.model_validate_json(path.read_text(encoding="utf-8"))


def save_tag_file(tag_file: TagFile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stable formatting keeps diffs readable when tags are corrected by hand.
    path.write_text(json.dumps(tag_file.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def merge_chunk_tags(existing: list[ChunkTag], new: list[ChunkTag]) -> list[ChunkTag]:
    """Use new tags, except for entries a human has already reviewed."""
    reviewed = {t.id: t for t in existing if t.reviewed}
    return [reviewed.get(tag.id, tag) for tag in new]


def merge_slide_tags(existing: list[SlideTag], new: list[SlideTag]) -> list[SlideTag]:
    reviewed = {t.number: t for t in existing if t.reviewed}
    return [reviewed.get(tag.number, tag) for tag in new]


def validate_tag_file(tag_file: TagFile, graph: ConceptGraph) -> list[str]:
    """Problems a reviewer should fix, e.g. typos in hand-edited concept ids."""
    problems = []
    for chunk in tag_file.chunks:
        problems += [
            f"chunk {chunk.id}: unknown concept {c}"
            for c in chunk.concept_ids
            if not graph.get_concept(c)
        ]
        if chunk.end < chunk.start:
            problems.append(f"chunk {chunk.id}: ends before it starts")
    for slide in tag_file.slides:
        problems += [
            f"slide {slide.number}: unknown concept {c}"
            for c in slide.concept_ids
            if not graph.get_concept(c)
        ]
    ids = [c.id for c in tag_file.chunks]
    if len(ids) != len(set(ids)):
        problems.append("duplicate chunk ids")
    return problems
