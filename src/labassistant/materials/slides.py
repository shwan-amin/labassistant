"""Slide PDF -> per-slide text and PNG thumbnails, with PyMuPDF."""

from pathlib import Path

import pymupdf

from labassistant.materials.models import Slide

THUMBNAIL_WIDTH = 480  # pixels; big enough to read a slide title in a side panel


def extract_slides(pdf_path: Path, thumbnail_dir: Path | None = None) -> list[Slide]:
    """One Slide per page. Thumbnails are written only if `thumbnail_dir` is given."""
    slides = []
    with pymupdf.open(pdf_path) as document:
        if thumbnail_dir is not None:
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
        for page in document:
            number = page.number + 1
            thumbnail_path = None
            if thumbnail_dir is not None:
                zoom = THUMBNAIL_WIDTH / page.rect.width
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
                target = thumbnail_dir / f"slide-{number:03d}.png"
                pixmap.save(target)
                thumbnail_path = str(target)
            slides.append(
                Slide(number=number, text=_clean(page.get_text()), thumbnail_path=thumbnail_path)
            )
    return slides


def _clean(text: str) -> str:
    """Collapse the ragged whitespace PDFs produce into readable lines."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
