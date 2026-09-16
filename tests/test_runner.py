from pathlib import Path

import pytest

from labassistant.knowledge import Task, load_task, load_topic
from labassistant.runner import RunStatus, TestStatus, list_test_names, run_submission

ROOT = Path(__file__).parent.parent
REFERENCE = (ROOT / "tasks" / "sum_nested" / "reference_solution.py").read_text()


@pytest.fixture(scope="module")
def task() -> Task:
    return load_task(ROOT / "tasks" / "sum_nested", load_topic("recursion", ROOT / "knowledge"))


def outcome(result, name):
    return next(t for t in result.tests if t.name == name)


def test_correct_solution_passes(task: Task) -> None:
    result = run_submission(REFERENCE, task)

    assert result.status == RunStatus.PASSED
    assert result.passed_count == len(list_test_names(task)) == 9
    assert result.failed_count == 0


def test_wrong_answer_reports_assertion_failures(task: Task) -> None:
    # Misconception: loop_return_exits_early
    code = """\
def sum_nested(items):
    for item in items:
        if isinstance(item, list):
            return sum_nested(item)
        return item
    return 0
"""
    result = run_submission(code, task)

    assert result.status == RunStatus.FAILED
    assert outcome(result, "test_empty_list_is_zero").status == TestStatus.PASSED
    flat = outcome(result, "test_flat_list")
    assert flat.status == TestStatus.FAILED
    assert flat.message == "assert 1 == 6"


def test_infinite_recursion_reported_as_error_with_line(task: Task) -> None:
    code = "def sum_nested(items):\n    return sum_nested(items)\n"
    result = run_submission(code, task)

    assert result.status == RunStatus.FAILED
    assert result.passed_count == 0
    first = result.tests[0]
    assert first.status == TestStatus.ERROR
    assert first.message.startswith("RecursionError")
    assert "solution.py:2" in first.details


def test_infinite_loop_times_out(task: Task) -> None:
    code = "def sum_nested(items):\n    while True:\n        pass\n"
    result = run_submission(code, task, timeout_seconds=2)

    assert result.status == RunStatus.TIMEOUT
    assert "2 seconds" in result.error_message
    assert result.duration_seconds < 5


def test_syntax_error_is_caught_before_running(task: Task) -> None:
    code = "def sum_nested(items)\n    return 0\n"
    result = run_submission(code, task)

    assert result.status == RunStatus.SYNTAX_ERROR
    assert result.error_line == 1
    assert result.tests == []


def test_missing_function_is_an_error(task: Task) -> None:
    result = run_submission("def total(items):\n    return 0\n", task)

    assert result.status == RunStatus.ERROR
    assert "cannot import name 'sum_nested'" in result.error_message


def test_exception_at_import_time_is_an_error(task: Task) -> None:
    result = run_submission("raise ValueError('boom')\n", task)

    assert result.status == RunStatus.ERROR
    assert "ValueError" in result.error_message


def test_network_access_is_blocked(task: Task) -> None:
    code = """\
import socket

def sum_nested(items):
    socket.create_connection(("example.com", 80), timeout=1)
    return 0
"""
    result = run_submission(code, task)

    assert result.passed_count == 0
    assert "not allowed in the sandbox" in result.tests[0].message


def test_subprocess_is_blocked(task: Task) -> None:
    code = """\
import subprocess

def sum_nested(items):
    subprocess.run(["echo", "hi"])
    return 0
"""
    result = run_submission(code, task)

    assert "subprocess.Popen" in result.tests[0].message


def test_secrets_are_not_visible(task: Task, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    code = """\
import os

def sum_nested(items):
    assert "ANTHROPIC_API_KEY" not in os.environ
    return 0
"""
    result = run_submission(code, task, test_names=["test_empty_list_is_zero"])

    assert result.status == RunStatus.PASSED


def test_selected_tests_only(task: Task) -> None:
    result = run_submission(REFERENCE, task, test_names=["test_flat_list", "test_deep_nesting"])

    assert result.status == RunStatus.PASSED
    assert sorted(t.name for t in result.tests) == ["test_deep_nesting", "test_flat_list"]


def test_unknown_test_names_rejected_without_running(task: Task) -> None:
    result = run_submission(REFERENCE, task, test_names=["test_flat_list", "--collect-only"])

    assert result.status == RunStatus.ERROR
    assert "unknown test names" in result.error_message


def test_results_do_not_contain_temp_paths(task: Task) -> None:
    result = run_submission("def sum_nested(items):\n    return sum_nested(items)\n", task)

    assert "labassistant-run-" not in result.model_dump_json()


def test_oversized_submission_rejected(task: Task) -> None:
    result = run_submission("x = 1\n" * 50_000, task)

    assert result.status == RunStatus.ERROR
    assert "too large" in result.error_message


def test_cpu_limit_applied_inside_sandbox(task: Task) -> None:
    code = """\
import resource

def sum_nested(items):
    soft, _ = resource.getrlimit(resource.RLIMIT_CPU)
    assert soft == 4, soft
    return 0
"""
    result = run_submission(code, task, test_names=["test_empty_list_is_zero"], timeout_seconds=3)

    assert result.status == RunStatus.PASSED, result.tests
