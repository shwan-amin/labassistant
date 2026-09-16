from fixtures import PROJECT_SPEC
from loader import build_tree
from report import render
from tree import Node


def test_render_single_file():
    assert render(Node.file("a.txt", 7)) == "a.txt (7 B)"


def test_render_nested_tree():
    expected = "\n".join(
        [
            "project/ (5550 B)",
            "  README.md (120 B)",
            "  src/ (430 B)",
            "    main.py (300 B)",
            "    utils/ (130 B)",
            "      strings.py (80 B)",
            "      maths.py (50 B)",
            "  docs/ (0 B)",
            "  data/ (5000 B)",
            "    big.csv (5000 B)",
        ]
    )
    assert render(build_tree("project", PROJECT_SPEC)) == expected
