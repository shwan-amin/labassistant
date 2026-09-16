"""The `run_tests` tool the diagnosis agent can call.

The tool is bound to one student's project. The model can:
* run the project's existing tests (all, or chosen test ids), or
* write a small **probe test** to check a hypothesis, e.g. "does total_size
  return 0 for an empty directory?".

Probe tests are for diagnosis only. They can contain code that exercises (or
even re-implements) the student's function, so they must never reach the
student. The probe code is kept on ToolExecution for internal logs, and is not
part of RunResult, which is what later stages may summarise.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from labassistant.context.models import ProjectFile
from labassistant.runner.models import RunResult, TestStatus
from labassistant.runner.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    PROBE_FILE_NAME,
    ProbeError,
    list_test_ids,
    run_project,
)

RUN_TESTS_TOOL_NAME = "run_tests"
MAX_LISTED_TEST_IDS = 60  # keep the tool description short for big projects


class RunTestsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_ids: list[str] | None = None
    probe_test_code: str | None = Field(default=None, min_length=1)


class ToolExecution(BaseModel):
    """What goes back to the model as a tool_result block, plus internal records."""

    content: str
    # True only when the tool itself could not run (bad input or invalid probe).
    # Failing tests are a normal result: they are the evidence the agent wants.
    is_error: bool = False
    result: RunResult | None = None
    # INTERNAL ONLY: for logs and evaluation. Never include in student-facing output.
    probe_code: str | None = None


def run_tests_tool_definition(files: list[ProjectFile]) -> dict[str, Any]:
    """Tool definition in Anthropic's format."""
    test_ids = list_test_ids(files)
    listed = ", ".join(test_ids[:MAX_LISTED_TEST_IDS]) or "(the project has no tests)"
    if len(test_ids) > MAX_LISTED_TEST_IDS:
        listed += f", ... and {len(test_ids) - MAX_LISTED_TEST_IDS} more"
    return {
        "name": RUN_TESTS_TOOL_NAME,
        "description": (
            "Run tests against the student's project, exactly as submitted, in a sandbox. "
            "Returns which tests passed or failed with error messages and short tracebacks "
            "that include file paths and line numbers.\n\n"
            "Either run the project's existing tests (omit both inputs for all tests, or pass "
            "test_ids), or pass probe_test_code: a small pytest file you write to check a "
            "specific hypothesis about the student's code. The probe runs on its own in the "
            f"project root as {PROBE_FILE_NAME}, so it can import project modules the same way "
            "the project's tests do. Probe tests are for your diagnosis only and are never "
            "shown to the student.\n\n"
            f"Existing test ids: {listed}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of existing test ids to run.",
                },
                "probe_test_code": {
                    "type": "string",
                    "description": (
                        "Optional pytest source for a probe test. When given, only the "
                        "probe runs. Define at least one test_ function."
                    ),
                },
            },
            "additionalProperties": False,
        },
    }


class RunTestsTool:
    """Executes `run_tests` calls for one project."""

    def __init__(
        self, files: list[ProjectFile], timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.files = files
        self.timeout_seconds = timeout_seconds
        self.definition = run_tests_tool_definition(files)

    def execute(self, tool_input: dict[str, Any]) -> ToolExecution:
        try:
            parsed = RunTestsInput.model_validate(tool_input)
        except ValidationError as exc:
            return ToolExecution(content=f"Invalid input for run_tests: {exc}", is_error=True)
        if parsed.test_ids and parsed.probe_test_code:
            return ToolExecution(
                content="Pass either test_ids or probe_test_code, not both.", is_error=True
            )

        try:
            result = run_project(
                self.files,
                test_ids=parsed.test_ids,
                probe_code=parsed.probe_test_code,
                timeout_seconds=self.timeout_seconds,
            )
        except ProbeError as exc:
            return ToolExecution(
                content=f"Probe test rejected: {exc}",
                is_error=True,
                probe_code=parsed.probe_test_code,
            )
        return ToolExecution(
            content=format_result_for_llm(result),
            result=result,
            probe_code=parsed.probe_test_code,
        )


def format_result_for_llm(result: RunResult) -> str:
    """A compact JSON summary. Passing tests are listed by id only, to save tokens."""
    summary: dict[str, Any] = {
        "status": result.status.value,
        "probe": result.probe,
        "passed": result.passed_count,
        "failed": result.failed_count,
    }
    if result.error_message:
        summary["error"] = result.error_message
    if result.error_path is not None:
        summary["error_file"] = result.error_path
    if result.error_line is not None:
        summary["error_line"] = result.error_line
    if result.tests:
        summary["passed_tests"] = [t.test_id for t in result.tests if t.status == TestStatus.PASSED]
        summary["failed_tests"] = [
            {
                "id": t.test_id,
                "status": t.status.value,
                "message": t.message,
                "traceback": t.details,
            }
            for t in result.tests
            if t.status in (TestStatus.FAILED, TestStatus.ERROR)
        ]
    return json.dumps(summary, indent=2)
