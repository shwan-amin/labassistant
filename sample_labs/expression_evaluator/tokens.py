"""Tokenizer for arithmetic expressions (provided, no changes needed)."""

from dataclasses import dataclass

OPERATORS = "+-*/()"


class ParseError(ValueError):
    """Raised for text that is not a valid expression."""


@dataclass(frozen=True)
class Token:
    kind: str  # "number" or "op"
    text: str


def tokenize(text: str) -> list[Token]:
    """Split `text` into number and operator tokens, ignoring spaces."""
    tokens = []
    position = 0
    while position < len(text):
        char = text[position]
        if char.isspace():
            position += 1
        elif char in OPERATORS:
            tokens.append(Token("op", char))
            position += 1
        elif char.isdigit() or char == ".":
            start = position
            while position < len(text) and (text[position].isdigit() or text[position] == "."):
                position += 1
            tokens.append(Token("number", text[start:position]))
        else:
            raise ParseError(f"unexpected character {char!r} at position {position}")
    return tokens
