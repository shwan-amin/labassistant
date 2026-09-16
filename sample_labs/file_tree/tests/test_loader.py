from fixtures import PROJECT_SPEC
from loader import build_tree


def test_empty_spec_gives_empty_directory():
    root = build_tree("root", {})
    assert root.is_directory
    assert root.children == []


def test_files_and_directories_are_built_in_order():
    root = build_tree("project", PROJECT_SPEC)
    assert [child.name for child in root.children] == ["README.md", "src", "docs", "data"]
    assert not root.children[0].is_directory
    assert root.children[0].size == 120
    assert root.children[1].is_directory


def test_nested_directories_are_built():
    root = build_tree("project", PROJECT_SPEC)
    utils = root.children[1].children[1]
    assert utils.name == "utils"
    assert [child.name for child in utils.children] == ["strings.py", "maths.py"]
