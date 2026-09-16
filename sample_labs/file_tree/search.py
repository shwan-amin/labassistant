"""Recursive searches over a directory tree."""

from metrics import total_size
from tree import Node


def find_path(node: Node, target: str) -> list[str] | None:
    """Names from `node` down to the first node called `target`, or None."""
    if node.name == target:
        return [node.name]
    for child in node.children:
        path = find_path(child, target)
        if path is not None:
            return [node.name] + path
    return None


def directories_larger_than(node: Node, limit: int) -> list[str]:
    """Names of directories whose total size exceeds `limit`, in pre-order."""
    if not node.is_directory:
        return []
    found = [node.name] if total_size(node) > limit else []
    for child in node.children:
        found.extend(directories_larger_than(child, limit))
    return found
