import pytest

from labassistant.diagnosis import find_leaks


@pytest.mark.parametrize(
    "text",
    [
        "Try this:\n```python\ndef total_size(node):\n    return 0\n```",
        "def count_files(node):",
        "    return 0",
        "return sum(sizes)",
        "count = 0",
        "total += child.size",
        "for child in node.children:",
        "if not node.children:",
        "else:",
        "from metrics import total_size",
        "Change it to `return 0` instead.",
        "Start with `count = 0` for directories.",
        "Loop with `for child in node.children` and add up.",
        "Use `lambda n: n.size` here.",
    ],
)
def test_code_is_flagged(text: str) -> None:
    assert find_leaks(text), text


@pytest.mark.parametrize(
    "text",
    [
        "The base case on line 24 returns a value that is too large for an empty directory.",
        "Look at what `count_files` returns for a directory with no children.",
        "Compare `node.children` with what the test `test_depth` expects.",
        "For example: what happens when the tree has only one file?",
        "Return values from each recursive call need to be combined.",
        "If the list is empty, what should the total be?",
        "The expression `count == 0` on line 3 is checked before the loop.",
        "See tests/test_metrics.py::test_count_files_ignores_directories and line 22.",
    ],
)
def test_explanations_are_not_flagged(text: str) -> None:
    assert find_leaks(text) == [], text
