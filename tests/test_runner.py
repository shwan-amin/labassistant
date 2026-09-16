import pytest

from labassistant.context import ProjectFile
from labassistant.runner import (
    ProbeError,
    RunStatus,
    TestStatus,
    list_test_ids,
    run_project,
)
from tests.context_helpers import files, load_lab


def with_change(project: list[ProjectFile], path: str, old: str, new: str) -> list[ProjectFile]:
    """A copy of the project with one textual edit, used to seed bugs."""
    changed = []
    for file in project:
        if file.path == path:
            assert old in file.content, f"{old!r} not in {path}"
            file = file.model_copy(update={"content": file.content.replace(old, new)})
        changed.append(file)
    return changed


@pytest.fixture(scope="module")
def file_tree() -> list[ProjectFile]:
    return load_lab("file_tree")


def outcome(result, test_id: str):
    return next(t for t in result.tests if t.test_id == test_id)


# --- the done-when cases ---


def test_correct_project_passes(file_tree) -> None:
    result = run_project(file_tree)

    assert result.status == RunStatus.PASSED
    assert result.passed_count == len(list_test_ids(file_tree)) == 16
    assert not result.probe


def test_wrong_answer_reports_assertion_failures(file_tree) -> None:
    # Misconception: base_case_wrong_value (empty directory counted as 1 file)
    project = with_change(file_tree, "metrics.py", "count = 0", "count = 1")
    result = run_project(project)

    assert result.status == RunStatus.FAILED
    failure = outcome(result, "tests/test_metrics.py::test_count_files_ignores_directories")
    assert failure.status == TestStatus.FAILED
    assert "assert 10 == 5" in failure.message
    assert outcome(result, "tests/test_metrics.py::test_depth").status == TestStatus.PASSED


def test_infinite_recursion_is_an_error_with_file_and_line(file_tree) -> None:
    # Misconception: recurses_on_whole_input
    project = with_change(
        file_tree,
        "metrics.py",
        "return sum(total_size(child) for child in node.children)",
        "return total_size(node)",
    )
    result = run_project(
        project, test_ids=["tests/test_metrics.py::test_total_size_of_nested_tree"]
    )

    assert result.status == RunStatus.FAILED
    [test] = result.tests
    assert test.status == TestStatus.ERROR
    assert test.message.startswith("RecursionError")
    assert "metrics.py:10" in test.details


def test_infinite_loop_times_out() -> None:
    project = files(
        {
            "loop.py": "def spin():\n    while True:\n        pass\n",
            "test_loop.py": "from loop import spin\n\ndef test_spin():\n    spin()\n",
        }
    )
    result = run_project(project, timeout_seconds=2)

    assert result.status == RunStatus.TIMEOUT
    assert "2 seconds" in result.error_message
    assert result.duration_seconds < 5


def test_syntax_error_reports_file_and_line(file_tree) -> None:
    project = with_change(
        file_tree,
        "search.py",
        "def find_path(node: Node, target: str)",
        "def find_path(node: Node, target: str",
    )
    result = run_project(project)

    assert result.status == RunStatus.SYNTAX_ERROR
    assert result.error_path == "search.py"
    assert result.error_line == 7
    assert result.tests == []


def test_probe_test_runs_alone_against_the_project(file_tree) -> None:
    probe = """\
from metrics import depth
from tree import Node


def test_directory_with_one_empty_subdirectory_has_depth_one():
    assert depth(Node.directory("d", [Node.directory("e")])) == 1


def test_probe_that_fails():
    assert depth(Node.file("f", 1)) == 99
"""
    result = run_project(file_tree, probe_code=probe)

    assert result.probe
    assert result.status == RunStatus.FAILED
    assert [t.file for t in result.tests] == ["test_labassistant_probe.py"] * 2
    assert result.passed_count == 1 and result.failed_count == 1


# --- more error handling ---


def test_import_error_in_one_module_still_runs_other_tests(file_tree) -> None:
    project = with_change(
        file_tree, "search.py", "from metrics import total_size", "from metrics import total"
    )
    result = run_project(project)

    assert result.status == RunStatus.FAILED
    assert "cannot import name 'total'" in result.error_message
    assert result.passed_count > 0
    assert not any(t.file == "tests/test_search.py" for t in result.tests)


def test_project_without_tests_is_an_error() -> None:
    result = run_project(files({"main.py": "x = 1\n"}))
    assert result.status == RunStatus.ERROR
    assert "no tests" in result.error_message


def test_selected_test_ids_only(file_tree) -> None:
    ids = ["tests/test_search.py::test_find_path_to_root", "tests/test_metrics.py::test_depth"]
    result = run_project(file_tree, test_ids=ids)

    assert result.status == RunStatus.PASSED
    assert sorted(t.test_id for t in result.tests) == sorted(ids)


def test_unknown_test_ids_rejected_without_running(file_tree) -> None:
    result = run_project(
        file_tree, test_ids=["tests/test_metrics.py::test_depth", "--collect-only"]
    )
    assert result.status == RunStatus.ERROR
    assert "unknown test ids" in result.error_message


def test_list_test_ids_includes_parametrised_functions_and_classes() -> None:
    project = files(
        {
            "tests/test_a.py": (
                "import pytest\n\n@pytest.mark.parametrize('x', [1])\ndef test_p(x):\n    pass\n"
            ),
            "tests/test_b.py": "class TestThing:\n    def test_m(self):\n        pass\n",
            "helper.py": "def test_not_a_test_file():\n    pass\n",
        }
    )
    assert list_test_ids(project) == [
        "tests/test_a.py::test_p",
        "tests/test_b.py::TestThing::test_m",
    ]


def test_class_based_test_ids_match_results() -> None:
    project = files({"test_c.py": "class TestC:\n    def test_ok(self):\n        assert True\n"})
    result = run_project(project, test_ids=["test_c.py::TestC::test_ok"])
    assert [t.test_id for t in result.tests] == ["test_c.py::TestC::test_ok"]


# --- probe validation (agent mistakes, not student mistakes) ---


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ("def test_x(:\n", "syntax error on line 1"),
        ("x = 1\n", "at least one function"),
        ("x = 1\n" * 5000, "larger than"),
    ],
)
def test_invalid_probes_raise(file_tree, probe: str, message: str) -> None:
    with pytest.raises(ProbeError, match=message):
        run_project(file_tree, probe_code=probe)


def test_probe_name_clash_raises() -> None:
    project = files({"test_labassistant_probe.py": "def test_a():\n    pass\n"})
    with pytest.raises(ProbeError, match="already has a file"):
        run_project(project, probe_code="def test_b():\n    pass\n")


# --- sandbox protections ---


def sandbox_project(test_body: str) -> list[ProjectFile]:
    return files({"test_sandbox.py": f"def test_inside_sandbox():\n{test_body}"})


def test_network_access_is_blocked() -> None:
    project = sandbox_project(
        "    import socket\n    socket.create_connection(('example.com', 80), timeout=1)\n"
    )
    result = run_project(project)
    assert "not allowed in the sandbox" in result.tests[0].message


def test_subprocess_is_blocked() -> None:
    result = run_project(
        sandbox_project("    import subprocess\n    subprocess.run(['echo', 'hi'])\n")
    )
    assert "subprocess.Popen" in result.tests[0].message


def test_secrets_are_not_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    result = run_project(
        sandbox_project("    import os\n    assert 'ANTHROPIC_API_KEY' not in os.environ\n")
    )
    assert result.status == RunStatus.PASSED


def test_cpu_limit_applied_inside_sandbox() -> None:
    body = "    import resource\n    assert resource.getrlimit(resource.RLIMIT_CPU)[0] == 4\n"
    result = run_project(sandbox_project(body), timeout_seconds=3)
    assert result.status == RunStatus.PASSED, result.tests


def test_original_project_is_not_modified(file_tree) -> None:
    writer = sandbox_project("    open('metrics.py', 'w').write('broken')\n")
    project = [*file_tree, *writer]
    run_project(project, test_ids=["test_sandbox.py::test_inside_sandbox"])

    assert "def total_size" in next(f for f in project if f.path == "metrics.py").content


def test_results_do_not_contain_temp_paths(file_tree) -> None:
    project = with_change(
        file_tree, "search.py", "from metrics import total_size", "from metrics import total"
    )
    result = run_project(project)

    dumped = result.model_dump_json()
    assert "labassistant-run-" not in dumped
    assert "/private" not in dumped


def test_oversized_project_rejected() -> None:
    project = files({"big.py": "x = 1\n" * 400_000, "test_a.py": "def test_a():\n    pass\n"})
    result = run_project(project)
    assert result.status == RunStatus.ERROR
    assert "too large" in result.error_message
