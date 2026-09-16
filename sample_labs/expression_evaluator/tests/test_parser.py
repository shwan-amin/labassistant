import pytest
from nodes import BinaryOp, Negate, Number
from parser import parse
from tokens import ParseError


def test_single_number():
    assert parse("42") == Number(42)


def test_precedence_multiplication_before_addition():
    assert parse("1 + 2 * 3") == BinaryOp("+", Number(1), BinaryOp("*", Number(2), Number(3)))


def test_left_associative_subtraction():
    assert parse("8 - 3 - 2") == BinaryOp("-", BinaryOp("-", Number(8), Number(3)), Number(2))


def test_brackets_override_precedence():
    assert parse("(1 + 2) * 3") == BinaryOp("*", BinaryOp("+", Number(1), Number(2)), Number(3))


def test_nested_negation():
    assert parse("--4") == Negate(Negate(Number(4)))


@pytest.mark.parametrize("text", ["", "1 +", "(1 + 2", "1 2", ")", "1 + * 2", "1..2"])
def test_invalid_expressions_raise_parse_error(text):
    with pytest.raises(ParseError):
        parse(text)
