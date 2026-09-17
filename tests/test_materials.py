import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from labassistant.config import Settings
from labassistant.knowledge import load_topic
from labassistant.llm import FakeLLMClient
from labassistant.materials import (
    ChunkTag,
    MaterialSource,
    SlideTag,
    TagFile,
    TranscriptSegment,
    retrieve,
)
from labassistant.materials.cli import build, review_lines
from labassistant.materials.retrieval import format_time
from labassistant.materials.slides import extract_slides
from labassistant.materials.tag_file import (
    load_tag_file,
    merge_chunk_tags,
    save_tag_file,
    validate_tag_file,
)
from labassistant.materials.tagging import TaggingItem, tag_items
from labassistant.materials.transcribe import chunk_segments, transcribe

ROOT = Path(__file__).parent.parent
GRAPH = load_topic("recursion", ROOT / "knowledge")


def source(**overrides) -> MaterialSource:
    data = {
        "id": "lec",
        "title": "Recursion Lecture",
        "page_url": "https://example.edu/lecture",
        "timestamp_url_template": "https://example.edu/video.mp4#t={seconds}",
        "slides_url": "https://example.edu/slides.pdf",
        "license": "CC BY-NC-SA 4.0",
        "attribution": "Example University",
    }
    data.update(overrides)
    return MaterialSource(**data)


def seg(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=end, text=text)


# --- chunking ---


def test_chunks_break_at_sentence_end_after_minimum_length() -> None:
    segments = [
        seg(0, 10, "Today we look at recursion"),
        seg(10, 25, "which means a function calls itself."),  # sentence end, but only 25s
        seg(25, 35, "Every recursion needs a base case."),  # 35s and sentence end: break
        seg(35, 50, "Now the recursive case"),
        seg(50, 70, "reduces the problem."),
    ]
    chunks = chunk_segments(segments, "lec")

    assert [(c.start, c.end) for c in chunks] == [(0, 35), (35, 70)]
    assert chunks[0].id == "lec-c001"
    assert chunks[0].text.startswith("Today we look at recursion which means")


def test_chunks_never_exceed_maximum_without_breaks() -> None:
    segments = [
        seg(i * 10, i * 10 + 10, "and then more words") for i in range(20)
    ]  # no sentence ends
    chunks = chunk_segments(segments, "lec")

    assert all(c.end - c.start <= 90 for c in chunks)
    assert chunks[0].end - chunks[0].start == 90
    assert chunks[-1].end == 200


def test_pause_is_a_break_point() -> None:
    segments = [seg(0, 31, "a long thought with no full stop"), seg(35, 70, "after a pause.")]
    assert [(c.start, c.end) for c in chunk_segments(segments, "lec")] == [(0, 31), (35, 70)]


def test_single_overlong_segment_is_its_own_chunk() -> None:
    chunks = chunk_segments([seg(0, 5, "Hi."), seg(5, 130, "a very long monologue")], "lec")
    assert [(c.start, c.end) for c in chunks] == [(0, 5), (5, 130)]


def test_short_final_chunk_joins_previous() -> None:
    segments = [seg(0, 40, "A complete first thought."), seg(40, 45, "Bye.")]
    assert [(c.start, c.end) for c in chunk_segments(segments, "lec")] == [(0, 45)]


def test_transcribe_uses_injected_model() -> None:
    class FakeWhisper:
        def transcribe(self, path, language, vad_filter):
            assert language == "en" and vad_filter
            return [
                SimpleNamespace(start=0.123, end=2.456, text=" Hello "),
                SimpleNamespace(start=3, end=4, text=" "),
            ], None

    assert transcribe(Path("x.mp4"), model=FakeWhisper()) == [seg(0.12, 2.46, "Hello")]


# --- slides ---


def make_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_extract_slides_text_and_thumbnails(tmp_path) -> None:
    pdf = tmp_path / "slides.pdf"
    make_pdf(pdf, ["BASE CASE   explained", "Dictionaries"])
    slides = extract_slides(pdf, tmp_path / "thumbs")

    assert [s.number for s in slides] == [1, 2]
    assert slides[0].text == "BASE CASE explained"
    assert Path(slides[0].thumbnail_path).read_bytes()[:4] == b"\x89PNG"


def test_extract_slides_without_thumbnails(tmp_path) -> None:
    pdf = tmp_path / "slides.pdf"
    make_pdf(pdf, ["one"])
    assert extract_slides(pdf)[0].thumbnail_path is None


# --- tagging ---


def test_tagging_batches_validates_and_warns() -> None:
    items = [TaggingItem(id=f"i{n}", text=f"text {n}") for n in range(3)]
    fake = FakeLLMClient(
        [
            FakeLLMClient.text(
                json.dumps(
                    {
                        "tags": [
                            {"id": "i0", "concept_ids": ["base_case", "pointers"]},
                            {"id": "i1", "concept_ids": []},
                        ]
                    }
                )
            ),
            FakeLLMClient.text(json.dumps({"tags": []})),  # model forgot i2
        ]
    )
    tags, usage, warnings = tag_items(fake, GRAPH, items, batch_size=2)

    assert tags == {"i0": ["base_case"], "i1": [], "i2": []}
    assert len(fake.calls) == 2
    assert "base_case" in fake.calls[0].system and "i0" in fake.calls[0].messages[0]["content"]
    assert any("pointers" in w for w in warnings) and any("i2" in w for w in warnings)
    assert usage.input_tokens > 0


# --- tag files ---


def test_tag_file_round_trip_and_reviewed_entries_survive_retagging(tmp_path) -> None:
    path = tmp_path / "lec.tags.json"
    reviewed = ChunkTag(id="c1", start=0, end=40, concept_ids=["call_stack"], reviewed=True)
    save_tag_file(TagFile(source=source(), chunks=[reviewed]), path)

    new = [
        ChunkTag(id="c1", start=0, end=40, concept_ids=["base_case"]),
        ChunkTag(id="c2", start=40, end=80),
    ]
    merged = merge_chunk_tags(load_tag_file(path).chunks, new)

    assert merged[0] == reviewed
    assert merged[1].id == "c2"


def test_validate_tag_file_reports_problems() -> None:
    tag_file = TagFile(
        source=source(),
        chunks=[
            ChunkTag(id="c1", start=0, end=10, concept_ids=["base_cas"]),
            ChunkTag(id="c1", start=10, end=20),
        ],
        slides=[SlideTag(number=3, concept_ids=["nope"])],
    )
    problems = validate_tag_file(tag_file, GRAPH)
    assert "chunk c1: unknown concept base_cas" in problems
    assert "slide 3: unknown concept nope" in problems
    assert "duplicate chunk ids" in problems


def test_committed_tag_files_are_valid() -> None:
    for path in (ROOT / "materials").glob("*.tags.json"):
        assert validate_tag_file(load_tag_file(path), GRAPH) == [], path


# --- retrieval ---


def tag_file_for_retrieval() -> TagFile:
    return TagFile(
        source=source(),
        chunks=[
            ChunkTag(
                id="c1",
                start=100,
                end=160,
                concept_ids=["base_case", "recursive_case", "call_stack"],
            ),
            ChunkTag(id="c2", start=200, end=260, concept_ids=["base_case"]),  # most focused
            ChunkTag(
                id="c3", start=300, end=360, concept_ids=["base_case", "call_stack"], reviewed=True
            ),
            ChunkTag(id="c4", start=400, end=460, concept_ids=["recursion_vs_iteration"]),
        ],
        slides=[
            SlideTag(number=4, concept_ids=["base_case", "recursive_case"]),
            SlideTag(number=9, concept_ids=["base_case"]),
        ],
    )


def test_retrieval_prefers_reviewed_then_focused_then_earlier(tmp_path) -> None:
    thumbs = tmp_path / "thumbnails" / "lec"
    thumbs.mkdir(parents=True)
    (thumbs / "slide-009.png").write_bytes(b"png")

    lecture, slide = retrieve(
        "base_case", [tag_file_for_retrieval()], GRAPH, thumbnail_root=tmp_path / "thumbnails"
    )

    assert lecture.kind == "lecture" and lecture.start_seconds == 300  # reviewed wins
    assert lecture.url == "https://example.edu/video.mp4#t=300"
    assert "5:00-6:00" in lecture.note and "base case" in lecture.note
    assert slide.slide_number == 9  # focused wins among unreviewed
    assert slide.thumbnail_path.endswith("slide-009.png")
    assert slide.attribution == "Example University"


def test_retrieval_without_reviews_picks_most_focused() -> None:
    tag_file = tag_file_for_retrieval()
    tag_file.chunks[2].reviewed = False
    [lecture, _] = retrieve("base_case", [tag_file], GRAPH)
    assert lecture.start_seconds == 200


def test_retrieval_with_nothing_tagged_and_page_url_fallback() -> None:
    tag_file = TagFile(
        source=source(timestamp_url_template=None, slides_url=None),
        chunks=[ChunkTag(id="c1", start=5, end=50, concept_ids=["call_stack"])],
    )
    assert retrieve("base_case", [tag_file], GRAPH) == []
    [lecture] = retrieve("call_stack", [tag_file], GRAPH)
    assert lecture.url == "https://example.edu/lecture"


def test_retrieval_unknown_concept() -> None:
    with pytest.raises(ValueError):
        retrieve("pointers", [], GRAPH)


def test_format_time() -> None:
    assert (format_time(59.9), format_time(252), format_time(3725)) == ("0:59", "4:12", "1:02:05")


# --- build pipeline end to end (fake whisper, fake LLM, generated PDF) ---


def test_build_and_review(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        materials_dir=tmp_path / "materials",
        processed_materials_dir=tmp_path / "processed",
    )
    pdf = tmp_path / "slides.pdf"
    make_pdf(pdf, ["BASE CASE", "DICTIONARIES"])

    class FakeWhisper:
        def transcribe(self, path, language, vad_filter):
            return [
                SimpleNamespace(start=0, end=40, text="The base case stops recursion."),
                SimpleNamespace(start=40, end=80, text="Dictionaries map keys."),
            ], None

    fake = FakeLLMClient(
        [
            FakeLLMClient.text(
                json.dumps(
                    {
                        "tags": [
                            {"id": "lec-c001", "concept_ids": ["base_case"]},
                            {"id": "lec-c002", "concept_ids": []},
                            {"id": "slide-1", "concept_ids": ["base_case"]},
                            {"id": "slide-2", "concept_ids": []},
                        ]
                    }
                )
            )
        ]
    )
    tag_file = build(
        source(),
        settings=settings,
        graph=GRAPH,
        client=fake,
        media=tmp_path / "x.mp4",
        slides_pdf=pdf,
        whisper=FakeWhisper(),
    )

    saved = load_tag_file(tmp_path / "materials" / "lec.tags.json")
    assert saved == tag_file
    assert [c.concept_ids for c in saved.chunks] == [["base_case"], []]
    assert [s.concept_ids for s in saved.slides] == [["base_case"], []]
    assert (tmp_path / "processed" / "lec" / "transcript.json").exists()
    assert (
        "text" not in (tmp_path / "materials" / "lec.tags.json").read_text()
    )  # no lecture text committed

    listing = "\n".join(review_lines(saved, settings, GRAPH))
    assert "The base case stops recursion." in listing  # local text shown for review
    assert "problems: none" in listing and "reviewed 0 of 4" in listing


def test_committed_lecture_has_reviewed_material_for_every_concept() -> None:
    """Retrieval on the real tag file returns a reviewed lecture moment and slide per concept."""
    tag_files = [load_tag_file(p) for p in (ROOT / "materials").glob("*.tags.json")]
    if not tag_files:
        pytest.skip("no tag files committed")
    reviewed_chunks = {(c.start, c.end) for tf in tag_files for c in tf.chunks if c.reviewed}
    reviewed_slides = {s.number for tf in tag_files for s in tf.slides if s.reviewed}

    for concept in GRAPH.concepts:
        links = {link.kind: link for link in retrieve(concept.id, tag_files, GRAPH)}
        assert set(links) == {"lecture", "slide"}, concept.id
        assert (links["lecture"].start_seconds, links["lecture"].end_seconds) in reviewed_chunks, (
            concept.id
        )
        assert links["slide"].slide_number in reviewed_slides, concept.id
