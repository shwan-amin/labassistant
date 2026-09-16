"""Decide which submitted project files are worth considering at all.

The extension already filters, but the backend cannot trust that, so it applies
the same rules again. Every skipped file is recorded with a reason.
"""

import fnmatch

from pydantic import BaseModel

from labassistant.context.models import ContextError, ProjectFile

# Folders that are never student-written code.
DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
}

# Machine-generated files: noisy for the LLM and not the student's work.
GENERATED_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.min.js",
    "*.map",
    "*.lock",
    "package-lock.json",
    "*.egg-info",
    ".DS_Store",
]


class SkippedFile(BaseModel):
    path: str
    reason: str


class FilterLimits(BaseModel):
    max_file_bytes: int = 200_000
    max_project_bytes: int = 2_000_000


class FilteredProject(BaseModel):
    files: list[ProjectFile]
    skipped: list[SkippedFile]


class GitignoreMatcher:
    """A deliberately small subset of .gitignore rules.

    Supported: comments, blank lines, `*`/`?` globs, trailing `/` for directories,
    leading `/` or a middle `/` to anchor to the project root, and `!` negation
    (the last matching rule wins). Only the root .gitignore is read.
    """

    def __init__(self, text: str) -> None:
        self.rules: list[tuple[str, bool, bool, bool]] = []  # pattern, negated, dir_only, anchored
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            line = line.removeprefix("!")
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/") or "/" in line
            self.rules.append((line.lstrip("/"), negated, dir_only, anchored))

    def is_ignored(self, path: str) -> bool:
        ignored = False
        for pattern, negated, dir_only, anchored in self.rules:
            if self._matches(path, pattern, dir_only, anchored):
                ignored = not negated
        return ignored

    @staticmethod
    def _matches(path: str, pattern: str, dir_only: bool, anchored: bool) -> bool:
        parts = path.split("/")
        # Every leading directory, e.g. "a/b/c.py" -> "a", "a/b".
        dir_prefixes = ["/".join(parts[:i]) for i in range(1, len(parts))]
        if anchored:
            candidates = dir_prefixes if dir_only else [*dir_prefixes, path]
            return any(fnmatch.fnmatchcase(c, pattern) for c in candidates)
        names = parts[:-1] if dir_only else parts
        return any(fnmatch.fnmatchcase(name, pattern) for name in names)


def filter_project(
    files: list[ProjectFile], selected_path: str, limits: FilterLimits | None = None
) -> FilteredProject:
    limits = limits or FilterLimits()
    by_path = {f.path: f for f in files}
    if selected_path not in by_path:
        raise ContextError(f"selected file {selected_path!r} was not included in the project files")

    gitignore = GitignoreMatcher(by_path[".gitignore"].content) if ".gitignore" in by_path else None

    kept: list[ProjectFile] = []
    skipped: list[SkippedFile] = []
    for file in sorted(by_path.values(), key=lambda f: f.path):
        reason = _skip_reason(file, gitignore, limits)
        if file.path == selected_path and reason:
            raise ContextError(f"selected file {selected_path!r} cannot be checked: {reason}")
        if reason:
            skipped.append(SkippedFile(path=file.path, reason=reason))
        else:
            kept.append(file)

    return _apply_project_cap(kept, skipped, selected_path, limits.max_project_bytes)


def _skip_reason(
    file: ProjectFile, gitignore: GitignoreMatcher | None, limits: FilterLimits
) -> str:
    parts = file.path.split("/")
    if any(part in DEFAULT_IGNORED_DIRS or part.endswith(".egg-info") for part in parts[:-1]):
        return "ignored directory"
    if gitignore and gitignore.is_ignored(file.path):
        return "matched .gitignore"
    if any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in GENERATED_PATTERNS):
        return "generated file"
    if "\x00" in file.content:
        return "binary file"
    if len(file.content.encode("utf-8")) > limits.max_file_bytes:
        return f"larger than {limits.max_file_bytes} bytes"
    return ""


def _apply_project_cap(
    kept: list[ProjectFile], skipped: list[SkippedFile], selected_path: str, cap: int
) -> FilteredProject:
    # The selected file always goes first so the cap can never remove it.
    ordered = sorted(kept, key=lambda f: (f.path != selected_path, f.path))
    within_cap: list[ProjectFile] = []
    total = 0
    for file in ordered:
        size = len(file.content.encode("utf-8"))
        if file.path != selected_path and total + size > cap:
            skipped.append(SkippedFile(path=file.path, reason=f"project size cap of {cap} bytes"))
            continue
        within_cap.append(file)
        total += size
    return FilteredProject(files=sorted(within_cap, key=lambda f: f.path), skipped=skipped)
