"""The sample labs are development and evaluation fixtures, so check they stay valid."""

import subprocess
import sys
from pathlib import Path

import pytest

SAMPLE_LABS = Path(__file__).parent.parent / "sample_labs"
LABS = sorted(path for path in SAMPLE_LABS.iterdir() if path.is_dir())


def source_files(lab: Path) -> list[Path]:
    return [p for p in lab.glob("*.py") if p.name != "conftest.py"]


def test_there_are_two_labs() -> None:
    assert [lab.name for lab in LABS] == ["expression_evaluator", "file_tree"]


@pytest.mark.parametrize("lab", LABS, ids=lambda lab: lab.name)
def test_lab_structure(lab: Path) -> None:
    assert (lab / "SPEC.md").exists()
    assert 3 <= len(source_files(lab)) <= 6
    assert list((lab / "tests").glob("test_*.py"))


@pytest.mark.parametrize("lab", LABS, ids=lambda lab: lab.name)
def test_recursion_crosses_files(lab: Path) -> None:
    """At least two modules define a function that calls itself."""
    import ast

    modules_with_recursion = set()
    for path in source_files(lab):
        tree = ast.parse(path.read_text())
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef):
                calls = {
                    node.func.id
                    for node in ast.walk(func)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                }
                if func.name in calls:
                    modules_with_recursion.add(path.name)
    assert len(modules_with_recursion) >= 2, modules_with_recursion


@pytest.mark.parametrize("lab", LABS, ids=lambda lab: lab.name)
def test_reference_version_passes_its_own_tests(lab: Path) -> None:
    # The reference labs are the author's own trusted code, so running them here is fine.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=lab,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
