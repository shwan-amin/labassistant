"""Text rendering of a directory tree."""

from metrics import total_size
from tree import Node


def render(node: Node, level: int = 0) -> str:
    """Indented listing, two spaces per level, one line per node."""
    indent = "  " * level
    if not node.is_directory:
        return f"{indent}{node.name} ({node.size} B)"
    lines = [f"{indent}{node.name}/ ({total_size(node)} B)"]
    for child in node.children:
        lines.append(render(child, level + 1))
    return "\n".join(lines)
