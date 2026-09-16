"""Recursive-descent parser: text -> AST."""

from nodes import BinaryOp, Negate, Node, Number
from tokens import ParseError, Token, tokenize


class _TokenStream:
    """Tracks our position in the token list."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.position = 0

    def peek(self) -> Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def next(self) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError("unexpected end of expression")
        self.position += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "op" and token.text in ops


def parse(text: str) -> Node:
    """Parse a whole expression, rejecting leftover tokens."""
    stream = _TokenStream(tokenize(text))
    node = parse_expression(stream)
    if stream.peek() is not None:
        raise ParseError(f"unexpected token {stream.peek().text!r}")
    return node


def parse_expression(stream: _TokenStream) -> Node:
    node = parse_term(stream)
    while stream.at_op("+", "-"):
        operator = stream.next().text
        node = BinaryOp(operator, node, parse_term(stream))
    return node


def parse_term(stream: _TokenStream) -> Node:
    node = parse_factor(stream)
    while stream.at_op("*", "/"):
        operator = stream.next().text
        node = BinaryOp(operator, node, parse_factor(stream))
    return node


def parse_factor(stream: _TokenStream) -> Node:
    if stream.at_op("-"):
        stream.next()
        return Negate(parse_factor(stream))
    if stream.at_op("("):
        stream.next()
        node = parse_expression(stream)
        if not stream.at_op(")"):
            raise ParseError("missing closing bracket")
        stream.next()
        return node
    token = stream.next()
    if token.kind != "number":
        raise ParseError(f"expected a number, got {token.text!r}")
    try:
        return Number(float(token.text))
    except ValueError as error:
        raise ParseError(f"invalid number {token.text!r}") from error
