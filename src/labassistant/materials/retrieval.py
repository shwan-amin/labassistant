"""Concept-tag retrieval: the best lecture chunk and slide for a concept gap.

Ranking, in order:
1. the item is tagged with the concept (required);
2. reviewed items before unreviewed ones (a human has checked them);
3. more focused items first: fewer other concepts tagged alongside it;
4. earlier in the lecture/deck first (concepts are usually introduced before
   they are combined with others).

Embedding retrieval is a separate experiment in the evaluation (Stage 10).
"""

from pathlib import Path

from labassistant.knowledge.schema import ConceptGraph
from labassistant.materials.models import ChunkTag, MaterialLink, SlideTag, TagFile


def load_all_tag_files(materials_dir: Path) -> list[TagFile]:
    from labassistant.materials.tag_file import load_tag_file

    return [load_tag_file(path) for path in sorted(materials_dir.glob("*.tags.json"))]


def retrieve(
    concept_id: str,
    tag_files: list[TagFile],
    graph: ConceptGraph,
    thumbnail_root: Path | None = None,
) -> list[MaterialLink]:
    """Up to one lecture link and one slide link for the concept (fewer if none are tagged)."""
    concept = graph.get_concept(concept_id)
    if concept is None:
        raise ValueError(f"unknown concept {concept_id!r}")

    links: list[MaterialLink] = []

    chunks = [(tf, c) for tf in tag_files for c in tf.chunks if concept_id in c.concept_ids]
    if chunks:
        tag_file, chunk = min(chunks, key=lambda pair: _chunk_rank(pair[1]))
        source = tag_file.source
        seconds = int(chunk.start)
        url = (
            source.timestamp_url_template.format(seconds=seconds)
            if source.timestamp_url_template
            else source.page_url
        )
        links.append(
            MaterialLink(
                kind="lecture",
                source_id=source.id,
                source_title=source.title,
                concept_id=concept_id,
                note=f"Watch {format_time(chunk.start)}-{format_time(chunk.end)} of "
                f'"{source.title}" for an explanation of {concept.name.lower()}.',
                url=url,
                start_seconds=chunk.start,
                end_seconds=chunk.end,
                attribution=source.attribution,
            )
        )

    slides = [(tf, s) for tf in tag_files for s in tf.slides if concept_id in s.concept_ids]
    if slides:
        tag_file, slide = min(slides, key=lambda pair: _slide_rank(pair[1]))
        source = tag_file.source
        thumbnail = None
        if thumbnail_root is not None:
            candidate = thumbnail_root / source.id / f"slide-{slide.number:03d}.png"
            thumbnail = str(candidate) if candidate.exists() else None
        links.append(
            MaterialLink(
                kind="slide",
                source_id=source.id,
                source_title=source.title,
                concept_id=concept_id,
                note=f'Slide {slide.number} of "{source.title}" covers {concept.name.lower()}.',
                url=source.slides_url or source.page_url,
                slide_number=slide.number,
                thumbnail_path=thumbnail,
                attribution=source.attribution,
            )
        )
    return links


def format_time(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _chunk_rank(chunk: ChunkTag) -> tuple:
    return (not chunk.reviewed, len(chunk.concept_ids), chunk.start)


def _slide_rank(slide: SlideTag) -> tuple:
    return (not slide.reviewed, len(slide.concept_ids), slide.number)
