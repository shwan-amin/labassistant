import json

import pytest

from labassistant.context import ProjectFile
from labassistant.runner import RUN_TESTS_TOOL_NAME, RunStatus, RunTestsTool
from tests.context_helpers import load_lab


@pytest.fixture(scope="module")
def expression_lab() -> list[ProjectFile]:
    return load_lab("expression_evaluator")


def test_definition_lists_test_ids_and_probe_input(expression_lab) -> None:
    definition = RunTestsTool(expression_lab).definition

    assert definition["name"] == RUN_TESTS_TOOL_NAME
    properties = definition["input_schema"]["properties"]
    assert set(properties) == {"test_ids", "probe_test_code"}
    assert "tests/test_parser.py::test_single_number" in definition["description"]
    assert "never shown to the student" in definition["description"]


def test_execute_all_tests_returns_compact_summary(expression_lab) -> None:
    execution = RunTestsTool(expression_lab).execute({})

    assert not execution.is_error
    assert execution.result is not None and execution.result.status == RunStatus.PASSED
    summary = json.loads(execution.content)
    assert summary["status"] == "passed"
    assert summary["probe"] is False
    assert summary["failed_tests"] == []
    assert execution.probe_code is None


def test_execute_probe_keeps_code_out_of_the_result(expression_lab) -> None:
    probe = (
        "from evaluator import evaluate\nfrom parser import parse\n\n"
        "def test_unary_minus_binds_tighter():\n    assert evaluate(parse('-2 * 3')) == -6\n"
    )
    execution = RunTestsTool(expression_lab).execute({"probe_test_code": probe})

    summary = json.loads(execution.content)
    assert summary["probe"] is True
    assert summary["passed_tests"] == ["test_labassistant_probe.py::test_unary_minus_binds_tighter"]
    assert execution.probe_code == probe  # kept for internal logs...
    assert "evaluate(parse" not in execution.content  # ...but not echoed in the result
    assert "evaluate(parse" not in execution.result.model_dump_json()


def test_invalid_probe_is_a_tool_error(expression_lab) -> None:
    execution = RunTestsTool(expression_lab).execute({"probe_test_code": "def test(:\n"})

    assert execution.is_error
    assert "Probe test rejected" in execution.content


@pytest.mark.parametrize(
    "bad_input",
    [
        {"test_ids": "tests/test_parser.py::test_single_number"},
        {"code": "print(1)"},
        {
            "test_ids": ["tests/test_parser.py::test_single_number"],
            "probe_test_code": "def test_a(): pass",
        },
    ],
)
def test_bad_input_is_a_tool_error(expression_lab, bad_input) -> None:
    assert RunTestsTool(expression_lab).execute(bad_input).is_error


def test_syntax_error_summary_includes_file_and_line(expression_lab) -> None:
    broken = [
        f.model_copy(update={"content": "def evaluate(node)\n"}) if f.path == "evaluator.py" else f
        for f in expression_lab
    ]
    summary = json.loads(RunTestsTool(broken).execute({}).content)

    assert summary["status"] == "syntax_error"
    assert summary["error_file"] == "evaluator.py"
    assert summary["error_line"] == 1
