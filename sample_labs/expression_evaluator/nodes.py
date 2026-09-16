"""AST node classes (provided, no changes needed)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class Negate:
    operand: "Node"


@dataclass(frozen=True)
class BinaryOp:
    operator: str  # one of + - * /
    left: "Node"
    right: "Node"


Node = Number | Negate | BinaryOp
