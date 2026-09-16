import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from labassistant.knowledge import ConceptGraph, TaskError, load_task, load_topic

ROOT = Path(__file__).parent.parent
TASK_DIR = ROOT / "tasks" / "sum_nested"


@pytest.fixture
def recursion() -> ConceptGraph:
    return load_topic("recursion", ROOT / "knowledge")


def copy_task(tmp_path: Path) -> Path:
    target = tmp_path / "sum_nested"
    shutil.copytree(TASK_DIR, target)
    return target


def edit_task_json(task_dir: Path, **changes: object) -> None:
    path = task_dir / "task.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def test_sum_nested_task_loads(recursion: ConceptGraph) -> None:
    task = load_task(TASK_DIR, recursion)
    assert task.function_name == "sum_nested"
    assert "sum_nested" in task.spec()
    assert set(task.target_concepts) <= recursion.concept_ids


def test_reference_solution_passes_task_tests(tmp_path: Path) -> None:
    # The reference solution is our own trusted code, so running it here is fine.
    # Untrusted submissions will only ever go through the Stage 2 runner.
    shutil.copy(TASK_DIR / "reference_solution.py", tmp_path / "solution.py")
    shutil.copy(TASK_DIR / "test_solution.py", tmp_path / "test_solution.py")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_solution.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_task_with_unknown_concept_is_rejected(tmp_path: Path, recursion: ConceptGraph) -> None:
    task_dir = copy_task(tmp_path)
    edit_task_json(task_dir, target_concepts=["base_case", "pointers"])
    with pytest.raises(TaskError, match="unknown concepts: \\['pointers'\\]"):
        load_task(task_dir, recursion)


def test_task_for_other_topic_is_rejected(tmp_path: Path, recursion: ConceptGraph) -> None:
    task_dir = copy_task(tmp_path)
    edit_task_json(task_dir, topic="sorting")
    with pytest.raises(TaskError, match="topic 'sorting'"):
        load_task(task_dir, recursion)


def test_task_missing_file_is_rejected(tmp_path: Path, recursion: ConceptGraph) -> None:
    task_dir = copy_task(tmp_path)
    (task_dir / "test_solution.py").unlink()
    with pytest.raises(TaskError, match="missing test_solution.py"):
        load_task(task_dir, recursion)


def test_task_without_task_json_is_rejected(tmp_path: Path, recursion: ConceptGraph) -> None:
    with pytest.raises(TaskError, match="missing task.json"):
        load_task(tmp_path, recursion)
