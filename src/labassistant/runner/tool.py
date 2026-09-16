"""The `run_tests` tool the diagnosis agent can call.

The tool is bound to one student's submission. The model can choose *which* tests
to run, but cannot pass in code. That keeps the evidence tied to what the student
actually wrote, and stops the model testing its own "fixed" version.
"""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from labassistant.knowledge.tasks import Task
from labassistant.runner.models import RunResult, TestStatus
from labassistant.runner.sandbox import DEFAULT_TIMEOUT_SECONDS, list_test_names, run_submission

RUN_TESTS_TOOL_NAME = "run_tests"


class RunTestsInput(BaseModel):
    test_names: list[str] | None = None


class ToolExecution(BaseModel):
    """What goes back to the model as a tool_result block."""

    content: str
    # True only when the tool itself could not run (bad input). Failing tests are
    # a normal, successful result: they are the evidence the agent is looking for.
    is_error: bool = False
    result: RunResult | None = None


def run_tests_tool_definition(task: Task) -> dict[str, Any]:
    """Tool definition in Anthropic's format. Test names are listed so the model can pick some."""
    names = ", ".join(list_test_names(task))
    return {
        "name": RUN_TESTS_TOOL_NAME,
        "description": (
            "Run the student's submitted code against the task's test suite in a sandbox and "
            "return which tests passed or failed, with error messages and short tracebacks that "
            "include line numbers in solution.py. Use this to gather evidence before diagnosing. "
            "It always runs the student's code exactly as submitted. Omit test_names to run all "
            f"tests. Available tests: {names}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of test function names to run.",
                }
            },
            "additionalProperties": False,
        },
    }


class RunTestsTool:
    """Executes `run_tests` calls for one submission."""

    def __init__(self, task: Task, code: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.task = task
        self.code = code
        self.timeout_seconds = timeout_seconds
        self.definition = run_tests_tool_definition(task)

    def execute(self, tool_input: dict[str, Any]) -> ToolExecution:
        try:
            parsed = RunTestsInput.model_validate(tool_input)
        except ValidationError as exc:
            return ToolExecution(content=f"Invalid input for run_tests: {exc}", is_error=True)

        result = run_submission(
            self.code,
            self.task,
            test_names=parsed.test_names,
            timeout_seconds=self.timeout_seconds,
        )
        return ToolExecution(content=format_result_for_llm(result), result=result)


def format_result_for_llm(result: RunResult) -> str:
    """A compact JSON summary. Passing tests are listed by name only, to save tokens."""
    summary: dict[str, Any] = {
        "status": result.status.value,
        "passed": result.passed_count,
        "failed": result.failed_count,
    }
    if result.error_message:
        summary["error"] = result.error_message
    if result.error_line is not None:
        summary["error_line"] = result.error_line
    if result.tests:
        summary["passed_tests"] = [t.name for t in result.tests if t.status == TestStatus.PASSED]
        summary["failed_tests"] = [
            {"name": t.name, "status": t.status.value, "message": t.message, "traceback": t.details}
            for t in result.tests
            if t.status in (TestStatus.FAILED, TestStatus.ERROR)
        ]
    return json.dumps(summary, indent=2)
