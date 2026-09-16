"""Structured results from running a submission against a task's tests."""

from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PASSED = "passed"  # every selected test passed
    FAILED = "failed"  # tests ran, at least one failed or errored
    SYNTAX_ERROR = "syntax_error"  # the submission could not be parsed
    TIMEOUT = "timeout"  # the run exceeded its time limit and was killed
    ERROR = "error"  # tests could not run (e.g. missing function, crash)


class TestStatus(StrEnum):
    __test__ = False  # not a pytest test class

    PASSED = "passed"
    FAILED = "failed"  # an assertion did not hold
    ERROR = "error"  # an exception other than an assertion, e.g. RecursionError
    SKIPPED = "skipped"


class TestOutcome(BaseModel):
    # Tell pytest this is not a test class, despite the name.
    __test__ = False

    name: str
    status: TestStatus
    message: str = ""  # one-line summary, e.g. "RecursionError: maximum recursion depth exceeded"
    details: str = ""  # short traceback, truncated


class RunResult(BaseModel):
    status: RunStatus
    tests: list[TestOutcome] = Field(default_factory=list)
    # Set for SYNTAX_ERROR, TIMEOUT and ERROR to explain what went wrong.
    error_message: str = ""
    error_line: int | None = None
    output: str = ""  # pytest's console output, truncated
    duration_seconds: float = 0.0

    @property
    def passed_count(self) -> int:
        return sum(t.status == TestStatus.PASSED for t in self.tests)

    @property
    def failed_count(self) -> int:
        return sum(t.status in (TestStatus.FAILED, TestStatus.ERROR) for t in self.tests)
