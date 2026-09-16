"""Small builders shared by the context tests."""

from pathlib import Path
from textwrap import dedent

from labassistant.context import ContextRequest, LineRange, ProjectFile

SAMPLE_LABS = Path(__file__).parent.parent / "sample_labs"


def files(contents: dict[str, str]) -> list[ProjectFile]:
    """Build project files from {path: source}; source is dedented for readable tests."""
    return [ProjectFile(path=path, content=dedent(text)) for path, text in contents.items()]


def request(
    project: list[ProjectFile], path: str, start: int, end: int | None = None
) -> ContextRequest:
    return ContextRequest(
        files=project, selected_path=path, selection=LineRange(start=start, end=end or start)
    )


def load_lab(name: str) -> list[ProjectFile]:
    lab = SAMPLE_LABS / name
    return [
        ProjectFile(path=str(path.relative_to(lab)), content=path.read_text())
        for path in sorted(lab.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def find_line(project: list[ProjectFile], path: str, text: str) -> int:
    """1-based number of the first line in `path` containing `text`."""
    file = next(f for f in project if f.path == path)
    return next(i for i, line in enumerate(file.lines, start=1) if text in line)
