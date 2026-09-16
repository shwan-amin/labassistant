import pytest
from pydantic import ValidationError

from labassistant.context import ContextError, FilterLimits, LineRange, ProjectFile, filter_project
from labassistant.context.filtering import GitignoreMatcher

# --- models ---


def test_paths_are_normalised() -> None:
    assert ProjectFile(path="./src\\main.py", content="").path == "src/main.py"


@pytest.mark.parametrize("bad", ["", "../secret.py", "a/../../b.py", "/"])
def test_bad_paths_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        ProjectFile(path=bad, content="")


def test_line_range_validation_and_helpers() -> None:
    outer = LineRange(start=2, end=10)
    assert outer.contains(LineRange(start=3, end=4))
    assert not outer.contains(LineRange(start=9, end=11))
    assert outer.overlaps(LineRange(start=9, end=11))
    assert str(LineRange(start=4, end=4)) == "line 4"
    with pytest.raises(ValidationError):
        LineRange(start=5, end=4)
    with pytest.raises(ValidationError):
        LineRange(start=0, end=1)


# --- gitignore subset ---


@pytest.mark.parametrize(
    ("patterns", "path", "ignored"),
    [
        ("*.log", "logs/app.log", True),
        ("secrets/", "secrets/key.txt", True),
        ("secrets/", "secrets", False),  # dir-only pattern does not match a file
        ("/build.py", "build.py", True),
        ("/build.py", "tools/build.py", False),  # anchored to the root
        ("docs/*.md", "docs/a.md", True),
        ("docs/*.md", "other/docs/a.md", False),
        ("*.txt\n!keep.txt", "keep.txt", False),  # negation, last rule wins
        ("# comment\n\n*.tmp", "x.tmp", True),
    ],
)
def test_gitignore_matcher(patterns: str, path: str, ignored: bool) -> None:
    assert GitignoreMatcher(patterns).is_ignored(path) is ignored


# --- filtering ---


def make(path: str, content: str = "x = 1\n") -> ProjectFile:
    return ProjectFile(path=path, content=content)


def test_filter_records_reasons() -> None:
    project = [
        make("main.py"),
        make(".gitignore", "private/\n"),
        make("private/answers.py"),
        make(".venv/lib/site.py"),
        make("__pycache__/main.cpython-311.pyc"),
        make("uv.lock"),
        make("image.png", "\x89PNG\x00\x00"),
        make("huge.py", "x" * 500),
    ]
    result = filter_project(project, "main.py", FilterLimits(max_file_bytes=100))

    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons == {
        "private/answers.py": "matched .gitignore",
        ".venv/lib/site.py": "ignored directory",
        "__pycache__/main.cpython-311.pyc": "ignored directory",
        "uv.lock": "generated file",
        "image.png": "binary file",
        "huge.py": "larger than 100 bytes",
    }
    assert [f.path for f in result.files] == [".gitignore", "main.py"]


def test_project_cap_keeps_selected_file() -> None:
    project = [make("a.py", "a" * 60), make("b.py", "b" * 60), make("z_selected.py", "z" * 60)]
    result = filter_project(project, "z_selected.py", FilterLimits(max_project_bytes=100))

    assert [f.path for f in result.files] == ["z_selected.py"]
    assert {s.path for s in result.skipped} == {"a.py", "b.py"}


def test_selected_file_missing_or_filtered_is_an_error() -> None:
    with pytest.raises(ContextError, match="not included"):
        filter_project([make("a.py")], "b.py")
    with pytest.raises(ContextError, match="binary"):
        filter_project([make("a.py", "\x00")], "a.py")
