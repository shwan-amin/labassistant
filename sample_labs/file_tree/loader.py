"""Build a Node tree from a nested dict description."""

from tree import Node


def build_tree(name: str, spec: dict) -> Node:
    """Return a directory Node called `name` built from `spec`.

    Each value in `spec` is either an int (file size) or a dict (subdirectory).
    """
    children = []
    for child_name, value in spec.items():
        if isinstance(value, dict):
            children.append(build_tree(child_name, value))
        else:
            children.append(Node.file(child_name, value))
    return Node.directory(name, children)
