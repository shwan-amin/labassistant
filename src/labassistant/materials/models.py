"""Teaching material data: sources, lecture chunks, slides and the committed tag file.

What is committed vs kept local (licences such as CC BY-NC-SA require care):
* committed, in materials/<source_id>.tags.json: source metadata and links,
  timestamps, slide numbers, concept tags and review flags;
* local only, in data/raw/ (gitignored): media, slide PDFs, transcripts, slide
  text and thumbnails.
"""

from pydantic import BaseModel, Field, model_validator


class MaterialSource(BaseModel):
    id: str
    title: str
    lecturer: str = ""
    page_url: str  # public page for the material
    # Link to the recording at a time, e.g. "https://youtu.be/ID?t={seconds}".
    # None when the recording can't be linked at a timestamp.
    timestamp_url_template: str | None = None
    slides_url: str | None = None
    license: str
    license_url: str | None = None
    attribution: str


class TranscriptSegment(BaseModel):
    start: float  # seconds
    end: float
    text: str


class LectureChunk(BaseModel):
    """A 30-90 second piece of a lecture. `text` is local only (not in the tag file)."""

    id: str
    start: float
    end: float
    text: str = ""

    @model_validator(mode="after")
    def check_times(self) -> "LectureChunk":
        if self.end < self.start:
            raise ValueError("chunk ends before it starts")
        return self


class Slide(BaseModel):
    """One slide. `text` and `thumbnail_path` are local only."""

    number: int = Field(ge=1)
    text: str = ""
    thumbnail_path: str | None = None


class ChunkTag(BaseModel):
    id: str
    start: float
    end: float
    concept_ids: list[str] = Field(default_factory=list)
    reviewed: bool = False  # set to true by a human after checking the tags


class SlideTag(BaseModel):
    number: int = Field(ge=1)
    concept_ids: list[str] = Field(default_factory=list)
    reviewed: bool = False


class TagFile(BaseModel):
    source: MaterialSource
    chunks: list[ChunkTag] = Field(default_factory=list)
    slides: list[SlideTag] = Field(default_factory=list)


class MaterialLink(BaseModel):
    """What a student sees for a confirmed gap."""

    kind: str  # "lecture" or "slide"
    source_id: str
    source_title: str
    concept_id: str
    note: str
    url: str | None
    start_seconds: float | None = None
    end_seconds: float | None = None
    slide_number: int | None = None
    thumbnail_path: str | None = None  # local file, served by the API later
    attribution: str
