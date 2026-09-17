"""Lecture audio/video -> timestamped transcript -> 30-90 second chunks.

Transcription uses faster-whisper locally (free, no API). It is an optional
dependency: `uv sync --extra materials`. Chunking is a separate pure function so
it can be tested without audio.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from labassistant.materials.models import LectureChunk, TranscriptSegment

MIN_CHUNK_SECONDS = 30.0
MAX_CHUNK_SECONDS = 90.0
# A silence at least this long is a good place to end a chunk.
PAUSE_SECONDS = 1.5


def transcribe(
    media_path: Path, model_size: str = "small", model: Any = None
) -> list[TranscriptSegment]:
    """Timestamped segments for a media file. `model` can be injected in tests."""
    if model is None:
        from faster_whisper import WhisperModel  # heavy import, only when really transcribing

        # int8 on CPU keeps memory and time reasonable on a laptop.
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(media_path), language="en", vad_filter=True)
    return [
        TranscriptSegment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
        for s in segments
        if s.text.strip()
    ]


def chunk_segments(
    segments: Iterable[TranscriptSegment],
    source_id: str,
    min_seconds: float = MIN_CHUNK_SECONDS,
    max_seconds: float = MAX_CHUNK_SECONDS,
) -> list[LectureChunk]:
    """Group segments into chunks of roughly min..max seconds.

    Once a chunk is at least `min_seconds` long, it ends at the next natural break:
    a sentence end or a pause before the next segment. It always ends before it
    would exceed `max_seconds`. A single segment longer than the maximum becomes
    its own chunk rather than being split mid-sentence.
    """
    ordered = sorted(segments, key=lambda s: s.start)
    chunks: list[LectureChunk] = []
    current: list[TranscriptSegment] = []

    def close() -> None:
        if current:
            chunks.append(
                LectureChunk(
                    id=f"{source_id}-c{len(chunks) + 1:03d}",
                    start=current[0].start,
                    end=current[-1].end,
                    text=" ".join(s.text for s in current),
                )
            )
            current.clear()

    for index, segment in enumerate(ordered):
        if current and segment.end - current[0].start > max_seconds:
            close()
        current.append(segment)

        length = current[-1].end - current[0].start
        next_segment = ordered[index + 1] if index + 1 < len(ordered) else None
        pause_follows = (
            next_segment is not None and next_segment.start - segment.end >= PAUSE_SECONDS
        )
        sentence_ends = segment.text.rstrip().endswith((".", "?", "!"))
        if length >= min_seconds and (pause_follows or sentence_ends):
            close()

    close()
    return _merge_short_tail(chunks, source_id, min_seconds, max_seconds)


def _merge_short_tail(
    chunks: list[LectureChunk], source_id: str, min_seconds: float, max_seconds: float
) -> list[LectureChunk]:
    """A last chunk shorter than the minimum joins the previous one if that still fits."""
    if len(chunks) < 2:
        return chunks
    previous, last = chunks[-2], chunks[-1]
    if last.end - last.start >= min_seconds or last.end - previous.start > max_seconds:
        return chunks
    merged = LectureChunk(
        id=previous.id, start=previous.start, end=last.end, text=f"{previous.text} {last.text}"
    )
    return [*chunks[:-2], merged]
