from fixtures import PROJECT_SPEC
from loader import build_tree
from search import directories_larger_than, find_path


def test_find_path_to_root():
    assert find_path(build_tree("project", PROJECT_SPEC), "project") == ["project"]


def test_find_path_to_nested_file():
    root = build_tree("project", PROJECT_SPEC)
    assert find_path(root, "maths.py") == ["project", "src", "utils", "maths.py"]


def test_find_path_searches_later_siblings():
    root = build_tree("project", PROJECT_SPEC)
    assert find_path(root, "big.csv") == ["project", "data", "big.csv"]


def test_find_path_missing_returns_none():
    assert find_path(build_tree("project", PROJECT_SPEC), "nope.txt") is None


def test_directories_larger_than():
    root = build_tree("project", PROJECT_SPEC)
    assert directories_larger_than(root, 100) == ["project", "src", "utils", "data"]
    assert directories_larger_than(root, 1000) == ["project", "data"]
    assert directories_larger_than(root, 10_000) == []
