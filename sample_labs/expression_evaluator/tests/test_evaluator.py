import pytest
from evaluator import EvaluationError, count_operations, evaluate
from parser import parse


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7", 7),
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("8 - 3 - 2", 3),
        ("-(2 + 3) * 2", -10),
        ("10 / 4", 2.5),
        ("((((5))))", 5),
    ],
)
def test_evaluate(text, expected):
    assert evaluate(parse(text)) == expected


def test_division_by_zero():
    with pytest.raises(EvaluationError):
        evaluate(parse("1 / (2 - 2)"))


def test_deeply_nested_expression():
    text = "(" * 100 + "1" + ")" * 100
    assert evaluate(parse(text)) == 1


def test_count_operations():
    assert count_operations(parse("5")) == 0
    assert count_operations(parse("-5")) == 1
    assert count_operations(parse("1 + 2 * -3")) == 3
