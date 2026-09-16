"""Run an untrusted submission against a task's tests in a restricted subprocess.

Layers of protection, from strongest to weakest:
1. A separate process in a fresh temporary directory, killed (with any children)
   when the timeout expires.
2. A minimal environment, so secrets such as ANTHROPIC_API_KEY are not visible.
3. OS resource limits on CPU time and file size, set by the launcher (where supported).
4. A Python audit hook that blocks sockets, subprocesses and ctypes (see _launcher.py).

This is enough for a research prototype run on the author's machine. It is not
a hardened sandbox; an optional Docker runner is planned for that.
"""

import ast
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from labassistant.knowledge.tasks import Task
from labassistant.runner.models import RunResult, RunStatus, TestOutcome, TestStatus

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_CODE_BYTES = 100_000
MAX_OUTPUT_CHARS = 4_000
MAX_DETAILS_CHARS = 1_500
MAX_FILE_BYTES = 10 * 1024 * 1024  # stops runaway writes, including captured print output

LAUNCHER = Path(__file__).with_name("_launcher.py")


def list_test_names(task: Task) -> list[str]:
    """Test function names in the task's test file (trusted code, so parsing it is fine)."""
    tree = ast.parse(task.tests_path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def run_submission(
    code: str,
    task: Task,
    *,
    test_names: list[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> RunResult:
    """Run `code` as solution.py against the task's tests. Never raises for bad submissions."""
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return RunResult(status=RunStatus.ERROR, error_message="submission is too large")

    if syntax_problem := _check_syntax(code):
        return syntax_problem

    selected = _validate_test_names(task, test_names)
    if isinstance(selected, RunResult):
        return selected

    with tempfile.TemporaryDirectory(prefix="labassistant-run-") as tmp:
        workdir = Path(tmp)
        (workdir / "solution.py").write_text(code, encoding="utf-8")
        shutil.copy(task.tests_path, workdir / "test_solution.py")
        shutil.copy(LAUNCHER, workdir / "_launcher.py")
        return _run_pytest(workdir, selected, timeout_seconds)


def _check_syntax(code: str) -> RunResult | None:
    # ast.parse only builds a syntax tree; it does not execute anything.
    try:
        ast.parse(code, filename="solution.py")
    except SyntaxError as exc:
        return RunResult(
            status=RunStatus.SYNTAX_ERROR,
            error_message=f"{type(exc).__name__}: {exc.msg}",
            error_line=exc.lineno,
        )
    except (ValueError, RecursionError, MemoryError) as exc:  # e.g. null bytes, absurd nesting
        return RunResult(status=RunStatus.SYNTAX_ERROR, error_message=f"could not parse: {exc}")
    return None


def _validate_test_names(task: Task, test_names: list[str] | None) -> list[str] | RunResult:
    """Only allow names that exist in the test file, so nothing odd reaches pytest's arguments."""
    if not test_names:
        return []
    known = set(list_test_names(task))
    unknown = sorted(set(test_names) - known)
    if unknown:
        return RunResult(
            status=RunStatus.ERROR,
            error_message=f"unknown test names: {unknown}. Available: {sorted(known)}",
        )
    return list(dict.fromkeys(test_names))  # de-duplicate, keep order


def _run_pytest(workdir: Path, selected: list[str], timeout_seconds: float) -> RunResult:
    targets = [f"test_solution.py::{name}" for name in selected] or ["test_solution.py"]
    command = [
        sys.executable,
        "-I",  # isolated mode: ignore PYTHON* env vars and the user site-packages
        "_launcher.py",
        *targets,
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",  # don't write .pytest_cache
        "--junitxml=report.xml",
        "-o",
        "junit_family=xunit1",
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",  # deterministic set/dict ordering across runs
        # Read by _launcher.py, which applies OS resource limits to itself.
        "LABASSISTANT_CPU_SECONDS": str(int(timeout_seconds) + 1),
        "LABASSISTANT_MAX_FILE_BYTES": str(MAX_FILE_BYTES),
    }

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # A new process group lets us kill the submission and anything it spawned.
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        return RunResult(
            status=RunStatus.TIMEOUT,
            error_message=f"tests did not finish within {timeout_seconds:g} seconds "
            "(possible infinite loop or non-terminating recursion)",
            duration_seconds=round(time.monotonic() - started, 3),
        )
    duration = round(time.monotonic() - started, 3)

    tests = _parse_junit_report(workdir / "report.xml", workdir)
    output = _hide_workdir(output, workdir)
    return _summarise(process.returncode, tests, _truncate(output, MAX_OUTPUT_CHARS), duration)


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


def _hide_workdir(text: str, workdir: Path) -> str:
    """Remove the random temp directory from paths.

    It is noise for the LLM, and because it changes on every run it would make
    identical submissions look different in the consistency experiments.
    """
    for path in {str(workdir.resolve()), str(workdir)}:
        text = text.replace(path + os.sep, "").replace(path, ".")
    return text


def _parse_junit_report(report_path: Path, workdir: Path) -> list[TestOutcome]:
    if not report_path.exists():
        return []
    try:
        xml_text = _hide_workdir(report_path.read_text(encoding="utf-8"), workdir)
        root = ET.fromstring(xml_text)
    except (ET.ParseError, UnicodeDecodeError):
        return []

    outcomes = []
    for case in root.iter("testcase"):
        status, message, details = TestStatus.PASSED, "", ""
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                message = (child.get("message") or "").strip()
                # Keep the end of the traceback: that is where the "E ..." lines are.
                details = _truncate_start((child.text or "").strip(), MAX_DETAILS_CHARS)
                if child.tag == "skipped":
                    status = TestStatus.SKIPPED
                elif child.tag == "error" or not _is_assertion(message):
                    # pytest reports any exception inside a test as a "failure";
                    # we separate genuine assertion failures from crashes like RecursionError.
                    status = TestStatus.ERROR
                else:
                    status = TestStatus.FAILED
        outcomes.append(
            TestOutcome(
                name=case.get("name", "?"),
                status=status,
                message=_first_line(message),
                details=details,
            )
        )
    return outcomes


def _is_assertion(message: str) -> bool:
    # pytest rewrites asserts, so a failed `assert x == y` is reported as "assert 1 == 6".
    return message.startswith(("assert ", "AssertionError"))


def _summarise(
    returncode: int, tests: list[TestOutcome], output: str, duration: float
) -> RunResult:
    # pytest exit codes: 0 all passed, 1 some tests failed, 2+ could not run properly.
    real_tests = [
        t for t in tests if t.name != "test_solution"
    ]  # collection errors appear as a module "test"
    if returncode == 0 and real_tests:
        status, error = RunStatus.PASSED, ""
    elif returncode == 1 and real_tests:
        status, error = RunStatus.FAILED, ""
    else:
        status = RunStatus.ERROR
        error = (
            _collection_error_message(tests, output) or f"test run failed (exit code {returncode})"
        )
        real_tests = []

    return RunResult(
        status=status,
        tests=real_tests,
        error_message=error,
        output=output,
        duration_seconds=duration,
    )


def _collection_error_message(tests: list[TestOutcome], output: str) -> str:
    """Find the most useful line, e.g. "ImportError: cannot import name 'sum_nested'"."""
    texts = [t.details for t in tests] + [output]
    for text in texts:
        for line in text.splitlines():
            if line.startswith("E ") and "Error" in line:
                return line[1:].strip()
    return next((t.message for t in tests if t.message), "")


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _truncate_start(text: str, limit: int) -> str:
    return text if len(text) <= limit else "[truncated] ...\n" + text[-limit:]
