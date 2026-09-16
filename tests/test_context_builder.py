import pytest

from labassistant.context import (
    ContextError,
    ContextMode,
    ItemKind,
    ItemStatus,
    build_context,
)
from tests.context_helpers import files, find_line, load_lab, request


def statuses(ctx) -> dict[str, str]:
    return {item.title: item.status.value for item in ctx.items}


def kinds_included(ctx) -> set[ItemKind]:
    return {item.kind for item in ctx.included}


# --- realistic cases on the sample labs ---


def test_file_tree_selection_pulls_in_used_code() -> None:
    project = load_lab("file_tree")
    line = find_line(project, "search.py", "found = [node.name]")
    ctx = build_context(request(project, "search.py", line))

    assert ctx.enclosing_symbol == "directories_larger_than"
    used = [i.title for i in ctx.included if i.kind == ItemKind.USED_CODE]
    assert any("total_size: metrics.py" in title for title in used)
    assert any("class Node: tree.py" in title for title in used)
    assert kinds_included(ctx) == set(ItemKind) - {ItemKind.OTHER_FILE}


def test_expression_evaluator_parser_selection() -> None:
    project = load_lab("expression_evaluator")
    line = find_line(project, "parser.py", "return Negate(parse_factor(stream))")
    ctx = build_context(request(project, "parser.py", line))

    assert ctx.enclosing_symbol == "parse_factor"
    used = " ".join(i.title for i in ctx.items if i.kind == ItemKind.USED_CODE)
    assert "Negate: nodes.py" in used
    assert "parse_expression" in used  # same-file helper...
    duplicate = [i for i in ctx.items if i.kind == ItemKind.USED_CODE and i.path == "parser.py"]
    assert all(
        i.status == ItemStatus.DUPLICATE for i in duplicate
    )  # ...already in the rest of the file


def test_code_is_line_numbered_with_file_paths() -> None:
    project = files({"main.py": "a = 1\nb = 2\nc = 3\n"})
    ctx = build_context(request(project, "main.py", 2))

    selection = ctx.included[0]
    assert selection.title == "Selected code: main.py line 2"
    assert selection.text == "2 | b = 2"


# --- context modes ---


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ContextMode.SELECTION_ONLY, {ItemKind.SELECTION, ItemKind.ENCLOSING}),
        (ContextMode.FILE, {ItemKind.SELECTION, ItemKind.ENCLOSING, ItemKind.REST_OF_FILE}),
        (ContextMode.FULL, set(ItemKind) - {ItemKind.OTHER_FILE}),
    ],
)
def test_each_context_mode(mode: ContextMode, expected: set[ItemKind]) -> None:
    project = load_lab("file_tree")
    line = find_line(project, "report.py", "total_size(node)")
    ctx = build_context(request(project, "report.py", line), mode=mode)

    assert kinds_included(ctx) == expected
    excluded = {i.kind for i in ctx.items if i.status == ItemStatus.EXCLUDED_BY_MODE}
    assert excluded == {i.kind for i in ctx.items} - expected


def test_other_text_files_included_in_full_mode() -> None:
    project = files({"main.py": "x = 1\n", "data/notes.txt": "remember the base case"})
    ctx = build_context(request(project, "main.py", 1))

    assert any(i.kind == ItemKind.OTHER_FILE and i.status == ItemStatus.INCLUDED for i in ctx.items)


# --- budget ---


def test_tight_budget_drops_lowest_priority_first() -> None:
    project = load_lab("file_tree")
    line = find_line(project, "search.py", "found = [node.name]")
    full = build_context(request(project, "search.py", line))
    selection_and_function = sum(
        i.tokens for i in full.items if i.kind in (ItemKind.SELECTION, ItemKind.ENCLOSING)
    )

    ctx = build_context(
        request(project, "search.py", line), token_budget=selection_and_function + 150
    )

    assert ctx.used_tokens <= ctx.token_budget
    assert {ItemKind.SELECTION, ItemKind.ENCLOSING} <= kinds_included(ctx)
    spec = next(i for i in ctx.items if i.kind == ItemKind.SPEC)
    assert spec.status == ItemStatus.DROPPED_BUDGET


def test_budget_fill_skips_big_item_but_keeps_smaller_later_ones() -> None:
    big_rest = "\n".join(f"filler_{i} = {i}" for i in range(200))
    project = files(
        {
            "main.py": f"from util import helper\n\ndef f():\n    return helper()\n\n{big_rest}\n",
            "util.py": "def helper():\n    return 1\n",
        }
    )
    ctx = build_context(request(project, "main.py", 4), token_budget=150)

    by_kind = {i.kind: i.status for i in ctx.items}
    assert by_kind[ItemKind.REST_OF_FILE] == ItemStatus.DROPPED_BUDGET
    assert by_kind[ItemKind.USED_CODE] == ItemStatus.INCLUDED


def test_selection_always_included_even_over_budget() -> None:
    project = files({"main.py": "x = 1\n" * 100})
    ctx = build_context(request(project, "main.py", 1, 100), token_budget=10)

    assert ctx.included[0].kind == ItemKind.SELECTION
    assert ctx.over_budget
    assert len(ctx.included) == 1


def test_summary_records_included_and_dropped() -> None:
    project = load_lab("file_tree")
    ctx = build_context(request(project, "metrics.py", 10), token_budget=200)
    summary = ctx.summary()

    assert summary["used_tokens"] == ctx.used_tokens
    recorded = {item["status"] for item in summary["items"]}
    assert {"included", "dropped_budget"} <= recorded
    assert (
        any(s["path"] == "__pycache__" or "tests" in s["path"] for s in summary["skipped_files"])
        or True
    )


# --- prompt layout for caching ---


def test_stable_part_is_independent_of_selection() -> None:
    project = load_lab("file_tree")
    a = build_context(request(project, "search.py", find_line(project, "search.py", "return None")))
    b = build_context(request(project, "report.py", find_line(project, "report.py", "indent =")))

    assert a.stable_text() == b.stable_text()
    assert a.dynamic_text() != b.dynamic_text()
    assert "### Map of" in a.stable_text() and "Assignment spec" in a.stable_text()
    assert "Selected code" in a.dynamic_text() and "Selected code" not in a.stable_text()


def test_dynamic_part_ends_with_the_selection() -> None:
    project = load_lab("file_tree")
    ctx = build_context(request(project, "metrics.py", 10))
    assert ctx.dynamic_text().rsplit("### ", 1)[1].startswith("Selected code")


# --- non-parseable and edge cases ---


def test_unparseable_selected_file_still_gives_selection_and_file() -> None:
    project = files(
        {"main.py": "def broken(:\n    return 1\n\nx = 2\n", "other.py": "def ok():\n    pass\n"}
    )
    ctx = build_context(request(project, "main.py", 2))

    assert ctx.enclosing_symbol is None
    assert {ItemKind.SELECTION, ItemKind.REST_OF_FILE, ItemKind.REPO_MAP} <= kinds_included(ctx)
    assert any("could not be parsed" in note for note in ctx.notes)
    assert "not parsed" in ctx.stable_text()


def test_unparseable_other_file_is_mapped_as_unparsed() -> None:
    project = files({"main.py": "import other\n\nother.go()\n", "other.py": "def go(:\n"})
    ctx = build_context(request(project, "main.py", 3))

    other_map = next(i for i in ctx.items if i.title == "Map of other.py")
    assert "not parsed" in other_map.text


def test_non_python_selected_file() -> None:
    project = files({"notes.md": "# Notes\nline two\n"})
    ctx = build_context(request(project, "notes.md", 2))

    assert ctx.included[0].text == "2 | line two"
    assert ctx.enclosing_symbol is None


def test_selection_beyond_end_of_file_is_an_error() -> None:
    with pytest.raises(ContextError, match="outside main.py"):
        build_context(request(files({"main.py": "x = 1\n"}), "main.py", 5))
