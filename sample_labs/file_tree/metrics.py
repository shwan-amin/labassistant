"""Recursive measurements of a directory tree."""

from tree import Node


def total_size(node: Node) -> int:
    """Size of a file, or the total size of every file inside a directory."""
    if not node.is_directory:
        return node.size
    return sum(total_size(child) for child in node.children)


def depth(node: Node) -> int:
    """0 for a file or empty directory, otherwise 1 + the deepest child."""
    if not node.is_directory or not node.children:
        return 0
    return 1 + max(depth(child) for child in node.children)


def count_files(node: Node) -> int:
    """Number of files (not directories) in the tree rooted at `node`."""
    if not node.is_directory:
        return 1
    count = 0
    for child in node.children:
        count += count_files(child)
    return count
