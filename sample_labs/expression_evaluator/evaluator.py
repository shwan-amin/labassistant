"""Recursive evaluation of an expression AST."""

from nodes import BinaryOp, Negate, Node, Number


class EvaluationError(ArithmeticError):
    """Raised when an expression cannot be evaluated, e.g. division by zero."""


def evaluate(node: Node) -> float:
    """Return the numeric value of `node`."""
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Negate):
        return -evaluate(node.operand)

    left = evaluate(node.left)
    right = evaluate(node.right)
    if node.operator == "+":
        return left + right
    if node.operator == "-":
        return left - right
    if node.operator == "*":
        return left * right
    if right == 0:
        raise EvaluationError("division by zero")
    return left / right


def count_operations(node: Node) -> int:
    """Number of BinaryOp and Negate nodes in the tree."""
    if isinstance(node, Number):
        return 0
    if isinstance(node, Negate):
        return 1 + count_operations(node.operand)
    assert isinstance(node, BinaryOp)
    return 1 + count_operations(node.left) + count_operations(node.right)
