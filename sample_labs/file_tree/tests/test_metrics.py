from fixtures import PROJECT_SPEC
from loader import build_tree
from metrics import count_files, depth, total_size
from tree import Node


def test_total_size_of_file_is_its_size():
    assert total_size(Node.file("a.txt", 42)) == 42


def test_total_size_of_empty_directory_is_zero():
    assert total_size(Node.directory("empty")) == 0


def test_total_size_of_nested_tree():
    assert total_size(build_tree("project", PROJECT_SPEC)) == 5550


def test_depth():
    assert depth(Node.file("a.txt", 1)) == 0
    assert depth(Node.directory("empty")) == 0
    assert depth(build_tree("project", PROJECT_SPEC)) == 3


def test_count_files_ignores_directories():
    assert count_files(build_tree("project", PROJECT_SPEC)) == 5
    assert count_files(Node.directory("empty")) == 0


def test_repeated_calls_give_the_same_answer():
    root = build_tree("project", PROJECT_SPEC)
    assert total_size(root) == total_size(root) == 5550
