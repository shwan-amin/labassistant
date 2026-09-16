"""Tests for the sum_nested task. The runner places the submission next to this file as solution.py.

Test names are descriptive on purpose: the diagnosis agent sees them as evidence.
"""

import copy

from solution import sum_nested


def test_empty_list_is_zero():
    assert sum_nested([]) == 0


def test_flat_list():
    assert sum_nested([1, 2, 3]) == 6


def test_single_level_nesting():
    assert sum_nested([1, [2, 3], 4]) == 10


def test_deep_nesting():
    assert sum_nested([1, [2, [3, [4, [5]]]]]) == 15


def test_empty_sublists():
    assert sum_nested([[], [[]], [[], []]]) == 0


def test_negative_numbers():
    assert sum_nested([-1, [-2, 3], [[-4]]]) == -4


def test_nested_list_first():
    assert sum_nested([[10, 20], 30]) == 60


def test_repeated_calls_are_independent():
    # Catches global or mutable default-argument accumulators.
    assert sum_nested([1, 2]) == 3
    assert sum_nested([1, 2]) == 3


def test_does_not_modify_input():
    data = [1, [2, [3]], 4]
    original = copy.deepcopy(data)
    sum_nested(data)
    assert data == original
