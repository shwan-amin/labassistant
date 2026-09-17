"""Build, review and query teaching material tag files. See materials/README.md."""

import argparse
import json
import sys
from pathlib import Path

from labassistant.config import Settings, get_settings
from labassistant.knowledge.loader import load_topic
from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.base import LLMClient
from labassistant.llm.factory import create_llm_client
from labassistant.materials.models import (
    ChunkTag,
    LectureChunk,
    MaterialSource,
    Slide,
    SlideTag,
    TagFile,
    TranscriptSegment,
)
from labassistant.materials.retrieval import format_time, load_all_tag_files, retrieve
from labassistant.materials.slides import extract_slides
from labassistant.materials.tag_file import (
    load_tag_file,
    merge_chunk_tags,
    merge_slide_tags,
    save_tag_file,
    validate_tag_file,
)
from labassistant.materials.tagging import TaggingItem, tag_items
from labassistant.materials.transcribe import chunk_segments, transcribe


def tag_file_path(settings: Settings, source_id: str) -> Path:
    return settings.materials_dir / f"{source_id}.tags.json"


def build(
    source: MaterialSource,
    *,
    settings: Settings,
    graph: ConceptGraph,
    client: LLMClient | None,
    media: Path | None,
    slides_pdf: Path | None,
    whisper_model: str = "small",
    whisper: object = None,
) -> TagFile:
    """Transcribe (cached), chunk, extract slides, tag with the LLM, and save the tag file."""
    processed = settings.processed_materials_dir / source.id
    processed.mkdir(parents=True, exist_ok=True)

    chunks: list[LectureChunk] = []
    if media is not None:
        transcript_path = processed / "transcript.json"
        if transcript_path.exists():
            segments = [TranscriptSegment(**s) for s in json.loads(transcript_path.read_text())]
        else:
            segments = transcribe(media, whisper_model, model=whisper)
            transcript_path.write_text(json.dumps([s.model_dump() for s in segments], indent=1))
        chunks = chunk_segments(segments, source.id)
        (processed / "chunks.json").write_text(
            json.dumps([c.model_dump() for c in chunks], indent=1)
        )

    slides: list[Slide] = []
    if slides_pdf is not None:
        slides = extract_slides(
            slides_pdf, settings.processed_materials_dir / "thumbnails" / source.id
        )
        (processed / "slides.json").write_text(
            json.dumps([s.model_dump() for s in slides], indent=1)
        )

    chunk_tags = {c.id: [] for c in chunks}
    slide_tags = {str(s.number): [] for s in slides}
    if client is not None:
        items = [TaggingItem(id=c.id, text=c.text) for c in chunks]
        items += [TaggingItem(id=f"slide-{s.number}", text=s.text) for s in slides]
        tags, usage, warnings = tag_items(client, graph, items)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(f"tagging usage: {usage}", file=sys.stderr)
        chunk_tags = {c.id: tags.get(c.id, []) for c in chunks}
        slide_tags = {str(s.number): tags.get(f"slide-{s.number}", []) for s in slides}

    path = tag_file_path(settings, source.id)
    existing = load_tag_file(path) if path.exists() else TagFile(source=source)
    tag_file = TagFile(
        source=source,
        chunks=merge_chunk_tags(
            existing.chunks,
            [
                ChunkTag(id=c.id, start=c.start, end=c.end, concept_ids=chunk_tags[c.id])
                for c in chunks
            ],
        )
        if chunks
        else existing.chunks,
        slides=merge_slide_tags(
            existing.slides,
            [SlideTag(number=s.number, concept_ids=slide_tags[str(s.number)]) for s in slides],
        )
        if slides
        else existing.slides,
    )
    save_tag_file(tag_file, path)
    return tag_file


def review_lines(tag_file: TagFile, settings: Settings, graph: ConceptGraph) -> list[str]:
    """Human-readable listing of tags next to the local text."""
    processed = settings.processed_materials_dir / tag_file.source.id
    chunk_text = _local_texts(processed / "chunks.json", "id")
    slide_text = _local_texts(processed / "slides.json", "number")

    lines = [f"# {tag_file.source.title}", ""]
    for chunk in tag_file.chunks:
        mark = "x" if chunk.reviewed else " "
        lines.append(
            f"[{mark}] {chunk.id} {format_time(chunk.start)}-{format_time(chunk.end)} "
            f"tags={chunk.concept_ids}"
        )
        lines.append(f"      {chunk_text.get(chunk.id, '(text not available locally)')[:300]}")
    lines.append("")
    for slide in tag_file.slides:
        mark = "x" if slide.reviewed else " "
        text = slide_text.get(str(slide.number), "(text not available locally)").replace(
            "\n", " / "
        )
        lines.append(f"[{mark}] slide {slide.number} tags={slide.concept_ids}")
        lines.append(f"      {text[:200]}")
    problems = validate_tag_file(tag_file, graph)
    lines.append("")
    lines.append("problems: none" if not problems else "problems:\n  " + "\n  ".join(problems))
    reviewed = sum(c.reviewed for c in tag_file.chunks) + sum(s.reviewed for s in tag_file.slides)
    lines.append(f"reviewed {reviewed} of {len(tag_file.chunks) + len(tag_file.slides)} entries")
    return lines


def _local_texts(path: Path, key: str) -> dict[str, str]:
    if not path.exists():
        return {}
    return {str(item[key]): item.get("text", "") for item in json.loads(path.read_text())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build_parser = commands.add_parser("build", help="transcribe, extract slides and tag")
    build_parser.add_argument("source", type=Path, help="materials/sources/<id>.json")
    build_parser.add_argument("--media", type=Path)
    build_parser.add_argument("--slides", type=Path)
    build_parser.add_argument("--whisper-model", default="small")
    build_parser.add_argument("--no-tag", action="store_true", help="skip LLM tagging")
    build_parser.add_argument("--topic", default="recursion")

    review_parser = commands.add_parser("review", help="show tags next to local text")
    review_parser.add_argument("source_id")
    review_parser.add_argument("--topic", default="recursion")

    retrieve_parser = commands.add_parser("retrieve", help="best material for a concept")
    retrieve_parser.add_argument("concept_id")
    retrieve_parser.add_argument("--topic", default="recursion")

    args = parser.parse_args(argv)
    settings = get_settings()
    graph = load_topic(args.topic, settings.knowledge_dir)

    if args.command == "build":
        source = MaterialSource.model_validate_json(args.source.read_text())
        client = None if args.no_tag else create_llm_client(settings)
        tag_file = build(
            source,
            settings=settings,
            graph=graph,
            client=client,
            media=args.media,
            slides_pdf=args.slides,
            whisper_model=args.whisper_model,
        )
        print(
            f"wrote {tag_file_path(settings, source.id)}: "
            f"{len(tag_file.chunks)} chunks, {len(tag_file.slides)} slides"
        )
    elif args.command == "review":
        path = tag_file_path(settings, args.source_id)
        if not path.exists():
            print(f"no tag file at {path}", file=sys.stderr)
            return 1
        print("\n".join(review_lines(load_tag_file(path), settings, graph)))
    else:
        links = retrieve(
            args.concept_id,
            load_all_tag_files(settings.materials_dir),
            graph,
            thumbnail_root=settings.processed_materials_dir / "thumbnails",
        )
        print(
            json.dumps([link.model_dump() for link in links], indent=2)
            if links
            else "no material tagged"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
