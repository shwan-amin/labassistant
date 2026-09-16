"""Turn an AST back into fully bracketed text."""

from nodes import Negate, Node, Number


def format_number(value: float) -> str:
    """Print whole numbers without a trailing .0."""
    return str(int(value)) if value.is_integer() else str(value)


def to_text(node: Node) -> str:
    if isinstance(node, Number):
        return format_number(node.value)
    if isinstance(node, Negate):
        return f"(-{to_text(node.operand)})"
    return f"({to_text(node.left)} {node.operator} {to_text(node.right)})"
