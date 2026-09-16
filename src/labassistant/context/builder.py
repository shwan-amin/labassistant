"""Assemble the context the diagnosis agent sees, within a token budget.

Two orders matter here, and they are different on purpose:

* **Priority order** decides what survives a tight budget:
  selection -> enclosing function -> rest of file -> directly used code
  -> repo map -> spec -> other text files.
* **Prompt order** decides how it is laid out: stable parts (repo map, spec,
  other files) first so prompt caching can reuse them across repeat checks, then
  the code that changes as the student edits, ending with the selection.
"""

import ast
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, Field

from labassistant.context.filtering import FilterLimits, SkippedFile, filter_project
from labassistant.context.models import (
    ContextError,
    ContextMode,
    ContextRequest,
    LineRange,
    ProjectFile,
)
from labassistant.context.python_analysis import (
    FileSummary,
    Symbol,
    find_enclosing_symbol,
    parse_python,
    summarise_python_file,
)
from labassistant.context.relevance import find_used_code
from labassistant.context.tokens import EstimatingTokenCounter, TokenCounter

SPEC_FILE_NAMES = ["SPEC.md", "spec.md", "ASSIGNMENT.md", "assignment.md", "README.md", "readme.md"]


class ItemKind(StrEnum):
    SELECTION = "selection"
    ENCLOSING = "enclosing"
    REST_OF_FILE = "rest_of_file"
    USED_CODE = "used_code"
    REPO_MAP = "repo_map"
    SPEC = "spec"
    OTHER_FILE = "other_file"


# Parts that rarely change between checks of the same project: rendered first for caching.
STABLE_KINDS = {ItemKind.REPO_MAP, ItemKind.SPEC, ItemKind.OTHER_FILE}

# Which kinds each mode allows. Everything else is recorded as "excluded by mode".
MODE_KINDS = {
    ContextMode.SELECTION_ONLY: {ItemKind.SELECTION, ItemKind.ENCLOSING},
    ContextMode.FILE: {ItemKind.SELECTION, ItemKind.ENCLOSING, ItemKind.REST_OF_FILE},
    ContextMode.FULL: set(ItemKind),
}

# Prompt order, top to bottom.
PROMPT_ORDER = [
    ItemKind.REPO_MAP,
    ItemKind.SPEC,
    ItemKind.OTHER_FILE,
    ItemKind.USED_CODE,
    ItemKind.REST_OF_FILE,
    ItemKind.ENCLOSING,
    ItemKind.SELECTION,
]


class ItemStatus(StrEnum):
    INCLUDED = "included"
    DROPPED_BUDGET = "dropped_budget"  # did not fit in the remaining budget
    EXCLUDED_BY_MODE = "excluded_by_mode"  # not part of the chosen context mode
    DUPLICATE = "duplicate"  # already covered by an included item


class ContextItem(BaseModel):
    kind: ItemKind
    path: str
    title: str
    text: str
    tokens: int
    lines: LineRange | None = None
    status: ItemStatus = ItemStatus.INCLUDED


class BuiltContext(BaseModel):
    mode: ContextMode
    token_budget: int
    selected_path: str
    selection: LineRange
    enclosing_symbol: str | None = None
    items: list[ContextItem]
    skipped_files: list[SkippedFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def included(self) -> list[ContextItem]:
        return [i for i in self.items if i.status == ItemStatus.INCLUDED]

    @property
    def used_tokens(self) -> int:
        return sum(i.tokens for i in self.included)

    @property
    def over_budget(self) -> bool:
        # Only possible when the selection alone is bigger than the budget.
        return self.used_tokens > self.token_budget

    def stable_text(self) -> str:
        return _render([i for i in self.included if i.kind in STABLE_KINDS])

    def dynamic_text(self) -> str:
        return _render([i for i in self.included if i.kind not in STABLE_KINDS])

    def summary(self) -> dict:
        """What was included or left out, for logs and the dashboard."""
        return {
            "mode": self.mode.value,
            "token_budget": self.token_budget,
            "used_tokens": self.used_tokens,
            "over_budget": self.over_budget,
            "items": [
                {
                    "kind": i.kind.value,
                    "title": i.title,
                    "tokens": i.tokens,
                    "status": i.status.value,
                }
                for i in self.items
            ],
            "skipped_files": [s.model_dump() for s in self.skipped_files],
            "notes": self.notes,
        }


def build_context(
    request: ContextRequest,
    *,
    mode: ContextMode = ContextMode.FULL,
    token_budget: int = 20_000,
    counter: TokenCounter | None = None,
    limits: FilterLimits | None = None,
) -> BuiltContext:
    counter = counter or EstimatingTokenCounter()
    project = filter_project(request.files, request.selected_path, limits)
    files = {f.path: f for f in project.files}
    selected = files[request.selected_path]

    line_count = len(selected.lines)
    if request.selection.end > line_count:
        raise ContextError(
            f"selection {request.selection} is outside {selected.path} ({line_count} lines)"
        )

    notes: list[str] = []
    summaries = {path: summarise_python_file(f) for path, f in files.items() if f.is_python}
    selected_summary = summaries.get(selected.path)
    if selected_summary and selected_summary.parse_error:
        notes.append(
            f"{selected.path} could not be parsed ({selected_summary.parse_error}); "
            "enclosing function and used code were not detected"
        )

    enclosing = (
        find_enclosing_symbol(selected_summary, request.selection)
        if selected_summary and not selected_summary.parse_error
        else None
    )

    candidates = _candidate_items(request, selected, files, summaries, enclosing, counter)
    items = _fill_budget(candidates, mode, token_budget)

    return BuiltContext(
        mode=mode,
        token_budget=token_budget,
        selected_path=selected.path,
        selection=request.selection,
        enclosing_symbol=enclosing.qualname if enclosing else None,
        items=items,
        skipped_files=project.skipped,
        notes=notes,
    )


# --- building candidate items, in priority order ---


def _candidate_items(
    request: ContextRequest,
    selected: ProjectFile,
    files: dict[str, ProjectFile],
    summaries: dict[str, FileSummary],
    enclosing: Symbol | None,
    counter: TokenCounter,
) -> list[ContextItem]:
    def make(kind: ItemKind, path: str, title: str, text: str, lines: LineRange | None = None):
        return ContextItem(
            kind=kind, path=path, title=title, text=text, tokens=counter.count(text), lines=lines
        )

    selection = request.selection
    items = [
        make(
            ItemKind.SELECTION,
            selected.path,
            f"Selected code: {selected.path} {selection}",
            _numbered(selected, selection),
            selection,
        )
    ]

    if enclosing is not None:
        items.append(
            make(
                ItemKind.ENCLOSING,
                selected.path,
                f"Enclosing {enclosing.kind} {enclosing.qualname}: "
                f"{selected.path} {enclosing.lines}",
                _numbered(selected, enclosing.lines),
                enclosing.lines,
            )
        )

    shown = enclosing.lines if enclosing else selection
    items.append(
        make(
            ItemKind.REST_OF_FILE,
            selected.path,
            f"Rest of {selected.path} ({shown} shown separately)",
            _numbered(selected, LineRange(start=1, end=max(1, len(selected.lines))), skip=shown),
            LineRange(start=1, end=max(1, len(selected.lines))),
        )
    )

    items.extend(_used_code_items(request, selected, files, summaries, enclosing, make))

    # Every Python file is mapped, including the selected one. That keeps the stable
    # part of the prompt identical whichever file is selected, so the cache can hit.
    for path, summary in summaries.items():
        if _has_map_content(summary):
            items.append(make(ItemKind.REPO_MAP, path, f"Map of {path}", _render_repo_map(summary)))

    spec_path = next((name for name in SPEC_FILE_NAMES if name in files), None)
    if spec_path:
        items.append(
            make(
                ItemKind.SPEC, spec_path, f"Assignment spec: {spec_path}", files[spec_path].content
            )
        )

    for path, file in files.items():
        if not file.is_python and path not in (spec_path, selected.path, ".gitignore"):
            items.append(make(ItemKind.OTHER_FILE, path, f"File: {path}", file.content))

    return items


MakeItem = Callable[..., ContextItem]


def _used_code_items(
    request: ContextRequest,
    selected: ProjectFile,
    files: dict[str, ProjectFile],
    summaries: dict[str, FileSummary],
    enclosing: Symbol | None,
    make: MakeItem,
) -> list[ContextItem]:
    selected_summary = summaries.get(selected.path)
    if selected_summary is None or selected_summary.parse_error:
        return []
    tree = parse_python(selected)
    assert isinstance(tree, ast.Module)  # it parsed a moment ago

    # Look at the whole enclosing function, not just the highlighted lines: the
    # student is asking about code whose meaning depends on the rest of the function.
    region = enclosing.lines if enclosing else request.selection
    items = []
    for used in find_used_code(tree, selected_summary, region, summaries, exclude=enclosing):
        file = files[used.path]
        if used.symbol is None:
            lines = LineRange(start=1, end=max(1, len(file.lines)))
            title = f"Used module {used.path} (via {used.via})"
        else:
            lines = used.symbol.lines
            title = f"Used {used.symbol.kind} {used.symbol.qualname}: {used.path} {lines}"
        items.append(make(ItemKind.USED_CODE, used.path, title, _numbered(file, lines), lines))
    return items


# --- choosing what fits ---


def _fill_budget(
    candidates: list[ContextItem], mode: ContextMode, budget: int
) -> list[ContextItem]:
    """Greedy fill in priority order.

    If an item does not fit we skip it but keep going, so a large file cannot
    crowd out several small, useful repo map entries after it.
    """
    used = 0
    included: list[ContextItem] = []
    for item in candidates:
        if item.kind not in MODE_KINDS[mode]:
            item.status = ItemStatus.EXCLUDED_BY_MODE
        elif item.kind == ItemKind.SELECTION:
            item.status = ItemStatus.INCLUDED  # always, even if it alone exceeds the budget
        elif _already_covered(item, included):
            item.status = ItemStatus.DUPLICATE
            item.tokens = 0
        elif used + item.tokens <= budget:
            item.status = ItemStatus.INCLUDED
        else:
            item.status = ItemStatus.DROPPED_BUDGET

        if item.status == ItemStatus.INCLUDED:
            used += item.tokens
            included.append(item)
    return candidates


def _already_covered(item: ContextItem, included: list[ContextItem]) -> bool:
    """Used code from the selected file is redundant if the whole file is already in."""
    if item.kind != ItemKind.USED_CODE or item.lines is None:
        return False
    return any(
        other.path == item.path
        and other.kind in (ItemKind.REST_OF_FILE, ItemKind.ENCLOSING)
        and other.lines is not None
        and other.lines.contains(item.lines)
        for other in included
    )


# --- rendering ---


def _numbered(file: ProjectFile, lines: LineRange, skip: LineRange | None = None) -> str:
    """Code with 1-based line numbers, so the model can cite exact lines."""
    source = file.lines
    width = len(str(len(source))) if source else 1
    out = []
    skipped_marker_written = False
    for number in range(lines.start, min(lines.end, len(source)) + 1):
        if skip and skip.start <= number <= skip.end:
            if not skipped_marker_written:
                out.append(f"{'':>{width}} | ... ({skip} shown separately) ...")
                skipped_marker_written = True
            continue
        out.append(f"{number:>{width}} | {source[number - 1]}")
    return "\n".join(out)


def _has_map_content(summary: FileSummary) -> bool:
    return bool(
        summary.parse_error or summary.module_docstring or summary.imports or summary.symbols
    )


def _render_repo_map(summary: FileSummary) -> str:
    if summary.parse_error:
        return f"{summary.path}\n  (not parsed: {summary.parse_error})"
    lines = [summary.path]
    if summary.module_docstring:
        lines.append(f'  """{summary.module_docstring}"""')
    if summary.imports:
        imported = sorted(
            {f"{i.module}.{i.symbol}" if i.symbol else i.module for i in summary.imports}
        )
        lines.append(f"  imports: {', '.join(imported)}")
    for symbol in summary.symbols:
        parent_is_class = symbol.parent is not None and symbol.kind == "method"
        if not (symbol.is_top_level or parent_is_class):
            continue  # nested helper functions are left out to keep the map compact
        indent = "    " if parent_is_class else "  "
        doc = f"  # {symbol.docstring}" if symbol.docstring else ""
        lines.append(f"{indent}{symbol.signature}  [{symbol.lines}]{doc}")
    return "\n".join(lines)


def _render(items: list[ContextItem]) -> str:
    ordered = sorted(items, key=lambda i: PROMPT_ORDER.index(i.kind))
    return "\n\n".join(f"### {item.title}\n```\n{item.text}\n```" for item in ordered)
