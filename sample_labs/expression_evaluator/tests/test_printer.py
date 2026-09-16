from parser import parse
from printer import to_text


def test_number():
    assert to_text(parse("3")) == "3"
    assert to_text(parse("2.5")) == "2.5"


def test_binary_operations_are_bracketed():
    assert to_text(parse("1 + 2 * 3")) == "(1 + (2 * 3))"


def test_negation():
    assert to_text(parse("-(1 - 2)")) == "(-(1 - 2))"


def test_round_trip_preserves_value():
    from evaluator import evaluate

    for text in ["1 + 2 * 3", "(8 - 3) - 2", "-4 / (1 + 1)"]:
        assert evaluate(parse(to_text(parse(text)))) == evaluate(parse(text))
