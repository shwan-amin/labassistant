"""Run a student's project tests, or an agent-written probe test, in a restricted subprocess.

Layers of protection, from strongest to weakest:
1. A separate process working on a temporary *copy* of the project, killed
   (with any children) when the timeout expires.
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

from labassistant.context.models import ProjectFile
from labassistant.runner.models import RunResult, RunStatus, TestOutcome, TestStatus

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_PROJECT_BYTES = 2_000_000
MAX_PROBE_BYTES = 20_000
MAX_OUTPUT_CHARS = 4_000
MAX_DETAILS_CHARS = 1_500
MAX_FILE_BYTES = 10 * 1024 * 1024  # stops runaway writes, including captured print output

# The probe goes in the project root so it can import the student's modules the
# same way the project's own tests do.
PROBE_FILE_NAME = "test_labassistant_probe.py"
LAUNCHER = Path(__file__).with_name("_launcher.py")


class ProbeError(ValueError):
    """The probe test itself is invalid. This is the agent's mistake, not the student's."""


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def list_test_ids(files: list[ProjectFile]) -> list[str]:
    """IDs like "tests/test_metrics.py::test_depth" for test functions in the project.

    Found by parsing, never by running. Test methods in classes are listed as
    "file::Class::test_name". Files that don't parse contribute nothing.
    """
    ids = []
    for file in files:
        if not is_test_file(file.path):
            continue
        try:
            tree = ast.parse(file.content)
        except (SyntaxError, ValueError):
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                ids.append(f"{file.path}::{node.name}")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                ids.extend(
                    f"{file.path}::{node.name}::{item.name}"
                    for item in node.body
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test")
                )
    return ids


def run_project(
    files: list[ProjectFile],
    *,
    test_ids: list[str] | None = None,
    probe_code: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> RunResult:
    """Run the project's tests (all, or `test_ids`), or only `probe_code` if given.

    Never raises for problems in the student's code; those come back as a RunResult.
    Raises ProbeError if `probe_code` itself is invalid.
    """
    if probe_code is not None:
        _check_probe(probe_code, files)

    if sum(len(f.content.encode("utf-8")) for f in files) > MAX_PROJECT_BYTES:
        return RunResult(status=RunStatus.ERROR, error_message="project is too large to run")

    if syntax_problem := _check_project_syntax(files):
        return syntax_problem

    if probe_code is not None:
        targets = [PROBE_FILE_NAME]
    else:
        selected = _validate_test_ids(files, test_ids)
        if isinstance(selected, RunResult):
            return selected
        targets = selected

    with tempfile.TemporaryDirectory(prefix="labassistant-run-") as tmp:
        project_dir = Path(tmp) / "project"
        runner_dir = Path(tmp) / "runner"  # kept apart so it can't clash with student files
        runner_dir.mkdir()
        shutil.copy(LAUNCHER, runner_dir / "_launcher.py")
        _write_project(project_dir, files)
        if probe_code is not None:
            (project_dir / PROBE_FILE_NAME).write_text(probe_code, encoding="utf-8")

        result = _run_pytest(project_dir, runner_dir / "_launcher.py", targets, timeout_seconds)
        result.probe = probe_code is not None
        return result


# --- checks before running ---


def _check_probe(probe_code: str, files: list[ProjectFile]) -> None:
    if len(probe_code.encode("utf-8")) > MAX_PROBE_BYTES:
        raise ProbeError(f"probe test is larger than {MAX_PROBE_BYTES} bytes")
    if any(f.path == PROBE_FILE_NAME for f in files):
        raise ProbeError(f"the project already has a file called {PROBE_FILE_NAME}")
    try:
        tree = ast.parse(probe_code)
    except SyntaxError as exc:
        raise ProbeError(f"probe test has a syntax error on line {exc.lineno}: {exc.msg}") from exc
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test") for n in tree.body):
        raise ProbeError(
            "probe test must define at least one function whose name starts with 'test'"
        )


def _check_project_syntax(files: list[ProjectFile]) -> RunResult | None:
    # ast.parse only builds a syntax tree; it does not execute anything.
    for file in sorted(files, key=lambda f: f.path):
        if not file.is_python:
            continue
        try:
            ast.parse(file.content, filename=file.path)
        except SyntaxError as exc:
            return RunResult(
                status=RunStatus.SYNTAX_ERROR,
                error_message=f"{type(exc).__name__} in {file.path}: {exc.msg}",
                error_path=file.path,
                error_line=exc.lineno,
            )
        except (ValueError, RecursionError, MemoryError) as exc:  # e.g. null bytes
            return RunResult(
                status=RunStatus.SYNTAX_ERROR,
                error_message=f"could not parse {file.path}: {exc}",
                error_path=file.path,
            )
    return None


def _validate_test_ids(
    files: list[ProjectFile], test_ids: list[str] | None
) -> list[str] | RunResult:
    """Only allow IDs that exist in the project, so nothing odd reaches pytest's arguments."""
    known = list_test_ids(files)
    if not known:
        return RunResult(status=RunStatus.ERROR, error_message="the project has no tests")
    if not test_ids:
        return sorted({test_id.split("::")[0] for test_id in known})  # every test file
    unknown = sorted(set(test_ids) - set(known))
    if unknown:
        return RunResult(
            status=RunStatus.ERROR,
            error_message=f"unknown test ids: {unknown}. Available: {sorted(known)}",
        )
    return list(dict.fromkeys(test_ids))  # de-duplicate, keep order


def _write_project(project_dir: Path, files: list[ProjectFile]) -> None:
    for file in files:
        # ProjectFile paths are already normalised and cannot contain "..".
        target = project_dir / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")


# --- running ---


def _run_pytest(
    project_dir: Path, launcher: Path, targets: list[str], timeout_seconds: float
) -> RunResult:
    command = [
        sys.executable,
        "-I",  # isolated mode: ignore PYTHON* env vars and the user site-packages
        str(launcher),
        *targets,
        "-q",
        "--tb=short",
        # By default pytest stops everything if one test file fails to import. We want
        # the other files' results too: they show which parts of the project still work.
        "--continue-on-collection-errors",
        "-p",
        "no:cacheprovider",  # don't write .pytest_cache
        f"--junitxml={project_dir.parent / 'report.xml'}",
        "-o",
        "junit_family=xunit1",  # includes each test's file path
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",  # deterministic set/dict ordering across runs
        # Read by _launcher.py, which applies OS resource limits to itself.
        "LABASSISTANT_CPU_SECONDS": str(int(timeout_seconds) + 1),
        "LABASSISTANT_MAX_FILE_BYTES": str(MAX_FILE_BYTES),
    }

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=project_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # A new process group lets us kill the tests and anything they spawned.
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

    hide = [project_dir.parent]
    tests, collection_errors = _parse_junit_report(project_dir.parent / "report.xml", hide)
    output = _truncate(_hide_paths(output, hide), MAX_OUTPUT_CHARS)
    return _summarise(process.returncode, tests, collection_errors, output, duration)


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


# --- reading results ---


def _hide_paths(text: str, directories: list[Path]) -> str:
    """Remove the random temp directory from paths.

    It is noise for the LLM, and because it changes on every run it would make
    identical submissions look different in the consistency experiments.
    """
    for directory in directories:
        # On macOS /var is a symlink to /private/var, so the same folder has two
        # spellings. Replace the longer one first so no "/private" is left behind.
        for path in sorted({str(directory.resolve()), str(directory)}, key=len, reverse=True):
            text = text.replace(path + "/project/", "").replace(path + "/project", ".")
            text = text.replace(path + os.sep, "").replace(path, ".")
    return text


def _parse_junit_report(report_path: Path, hide: list[Path]) -> tuple[list[TestOutcome], list[str]]:
    """Returns (test outcomes, collection error messages)."""
    if not report_path.exists():
        return [], []
    try:
        root = ET.fromstring(_hide_paths(report_path.read_text(encoding="utf-8"), hide))
    except (ET.ParseError, UnicodeDecodeError):
        return [], []

    outcomes: list[TestOutcome] = []
    collection_errors: list[str] = []
    for case in root.iter("testcase"):
        status, message, details = TestStatus.PASSED, "", ""
        for child in case:
            if child.tag not in ("failure", "error", "skipped"):
                continue
            message = (child.get("message") or "").strip()
            # Keep the end of the traceback: that is where the "E ..." lines are.
            details = _truncate_start((child.text or "").strip(), MAX_DETAILS_CHARS)
            if child.tag == "skipped":
                status = TestStatus.SKIPPED
            elif child.tag == "error" or not _is_assertion(message):
                # pytest reports any exception inside a test as a "failure"; we separate
                # genuine assertion failures from crashes like RecursionError.
                status = TestStatus.ERROR
            else:
                status = TestStatus.FAILED

        if message == "collection failure":
            # A test module could not even be imported, e.g. ImportError in student code.
            collection_errors.append(
                _error_line(details) or f"could not collect {case.get('name')}"
            )
            continue
        outcomes.append(
            TestOutcome(
                file=case.get("file", ""),
                name=_test_name(case),
                status=status,
                message=_first_line(message),
                details=details,
            )
        )
    return outcomes, collection_errors


def _test_name(case: ET.Element) -> str:
    """Test name, with the class for methods: "TestThing::test_x"."""
    name = case.get("name", "?")
    classname = case.get("classname", "")
    last_part = classname.rsplit(".", 1)[-1]
    return f"{last_part}::{name}" if last_part.startswith("Test") else name


def _is_assertion(message: str) -> bool:
    # pytest rewrites asserts, so a failed `assert x == y` is reported as "assert 1 == 6".
    return message.startswith(("assert ", "AssertionError"))


def _summarise(
    returncode: int,
    tests: list[TestOutcome],
    collection_errors: list[str],
    output: str,
    duration: float,
) -> RunResult:
    # pytest exit codes: 0 all passed, 1 some failed, 2 interrupted/collection errors, 5 none ran.
    error = "; ".join(collection_errors)
    if tests and returncode == 0:
        status = RunStatus.PASSED
    elif tests:
        status = RunStatus.FAILED
    else:
        status = RunStatus.ERROR
        if not error:
            error = (
                "no tests ran" if returncode == 5 else f"test run failed (exit code {returncode})"
            )
            error = _error_line(output) or error
    return RunResult(
        status=status, tests=tests, error_message=error, output=output, duration_seconds=duration
    )


def _error_line(text: str) -> str:
    """The most useful line of a traceback, e.g. "ImportError: cannot import name 'depth'"."""
    for line in text.splitlines():
        if line.startswith("E ") and ("Error" in line or "Exception" in line):
            return line[1:].strip()
    return ""


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _truncate_start(text: str, limit: int) -> str:
    return text if len(text) <= limit else "[truncated] ...\n" + text[-limit:]
