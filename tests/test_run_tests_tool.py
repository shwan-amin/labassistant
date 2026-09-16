import json
from pathlib import Path

import pytest

from labassistant.knowledge import Task, load_task, load_topic
from labassistant.runner import RUN_TESTS_TOOL_NAME, RunStatus, RunTestsTool

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def task() -> Task:
    return load_task(ROOT / "tasks" / "sum_nested", load_topic("recursion", ROOT / "knowledge"))


def test_definition_has_anthropic_tool_shape(task: Task) -> None:
    tool = RunTestsTool(task, code="")

    assert tool.definition["name"] == RUN_TESTS_TOOL_NAME
    assert tool.definition["input_schema"]["type"] == "object"
    assert "test_deep_nesting" in tool.definition["description"]
    assert "code" not in tool.definition["input_schema"]["properties"]


def test_execute_returns_compact_json_summary(task: Task) -> None:
    code = "def sum_nested(items):\n    return 0\n"
    execution = RunTestsTool(task, code).execute({})

    assert not execution.is_error
    assert execution.result is not None and execution.result.status == RunStatus.FAILED
    summary = json.loads(execution.content)
    assert summary["status"] == "failed"
    assert "test_empty_list_is_zero" in summary["passed_tests"]
    failed_names = [t["name"] for t in summary["failed_tests"]]
    assert "test_flat_list" in failed_names


def test_execute_with_selected_tests(task: Task) -> None:
    reference = (ROOT / "tasks" / "sum_nested" / "reference_solution.py").read_text()
    execution = RunTestsTool(task, reference).execute({"test_names": ["test_flat_list"]})

    summary = json.loads(execution.content)
    assert summary == {
        "status": "passed",
        "passed": 1,
        "failed": 0,
        "passed_tests": ["test_flat_list"],
        "failed_tests": [],
    }


def test_invalid_input_is_a_tool_error(task: Task) -> None:
    execution = RunTestsTool(task, code="").execute({"test_names": "test_flat_list"})

    assert execution.is_error
    assert "Invalid input" in execution.content


def test_syntax_error_summary_includes_line(task: Task) -> None:
    execution = RunTestsTool(task, "def sum_nested(items)\n").execute({})

    summary = json.loads(execution.content)
    assert summary["status"] == "syntax_error"
    assert summary["error_line"] == 1
