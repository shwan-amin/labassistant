"""Teaching material: transcription, slide extraction, concept tagging and retrieval."""

from labassistant.materials.models import (
    ChunkTag,
    LectureChunk,
    MaterialLink,
    MaterialSource,
    Slide,
    SlideTag,
    TagFile,
    TranscriptSegment,
)
from labassistant.materials.retrieval import load_all_tag_files, retrieve

__all__ = [
    "ChunkTag",
    "LectureChunk",
    "MaterialLink",
    "MaterialSource",
    "Slide",
    "SlideTag",
    "TagFile",
    "TranscriptSegment",
    "load_all_tag_files",
    "retrieve",
]
