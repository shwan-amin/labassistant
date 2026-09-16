"""Structured results from running a project's tests or a probe test."""

from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PASSED = "passed"  # every test that ran passed
    FAILED = "failed"  # tests ran, at least one failed or errored
    SYNTAX_ERROR = "syntax_error"  # a project file could not be parsed
    TIMEOUT = "timeout"  # the run exceeded its time limit and was killed
    ERROR = "error"  # tests could not run (e.g. import failure, no tests found)


class TestStatus(StrEnum):
    __test__ = False  # not a pytest test class

    PASSED = "passed"
    FAILED = "failed"  # an assertion did not hold
    ERROR = "error"  # an exception other than an assertion, e.g. RecursionError
    SKIPPED = "skipped"


class TestOutcome(BaseModel):
    __test__ = False  # not a pytest test class

    file: str  # project-relative path, e.g. "tests/test_metrics.py"
    name: str  # e.g. "test_depth" or "test_evaluate[1 + 2 * 3-7]"
    status: TestStatus
    message: str = ""  # one-line summary, e.g. "RecursionError: maximum recursion depth exceeded"
    details: str = ""  # short traceback (the end of it), truncated

    @property
    def test_id(self) -> str:
        return f"{self.file}::{self.name}"


class RunResult(BaseModel):
    status: RunStatus
    tests: list[TestOutcome] = Field(default_factory=list)
    # True when this run was an agent-written probe test rather than the project's tests.
    probe: bool = False
    # Set for SYNTAX_ERROR, TIMEOUT and ERROR (and FAILED with collection errors).
    error_message: str = ""
    error_path: str | None = None
    error_line: int | None = None
    output: str = ""  # pytest's console output, truncated
    duration_seconds: float = 0.0

    @property
    def passed_count(self) -> int:
        return sum(t.status == TestStatus.PASSED for t in self.tests)

    @property
    def failed_count(self) -> int:
        return sum(t.status in (TestStatus.FAILED, TestStatus.ERROR) for t in self.tests)
