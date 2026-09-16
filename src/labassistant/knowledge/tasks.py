"""Programming tasks: metadata plus the files the code runner needs.

Each task lives in its own folder, e.g. tasks/sum_nested/:
    task.json               metadata (this model)
    spec.md                 what the student is asked to do
    reference_solution.py   a correct solution
    test_solution.py        pytest tests that import from `solution`
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from labassistant.knowledge.schema import ID_PATTERN, ConceptGraph


class TaskError(ValueError):
    """Raised when a task folder is incomplete or inconsistent with its concept graph."""


class Task(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    title: str
    topic: str = Field(pattern=ID_PATTERN)
    function_name: str
    # Concepts the task is designed to exercise; must exist in the topic's graph.
    target_concepts: list[str] = Field(min_length=1)
    directory: Path

    @property
    def spec_path(self) -> Path:
        return self.directory / "spec.md"

    @property
    def reference_solution_path(self) -> Path:
        return self.directory / "reference_solution.py"

    @property
    def tests_path(self) -> Path:
        return self.directory / "test_solution.py"

    def spec(self) -> str:
        return self.spec_path.read_text(encoding="utf-8")


def load_task(task_dir: Path, graph: ConceptGraph) -> Task:
    try:
        raw = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        task = Task.model_validate({**raw, "directory": task_dir})
    except FileNotFoundError as exc:
        raise TaskError(f"missing task.json in {task_dir}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise TaskError(f"invalid task.json in {task_dir}:\n{exc}") from exc

    if task.topic != graph.topic:
        raise TaskError(f"task '{task.id}' is for topic '{task.topic}', not '{graph.topic}'")

    unknown = sorted(set(task.target_concepts) - graph.concept_ids)
    if unknown:
        raise TaskError(f"task '{task.id}' targets unknown concepts: {unknown}")

    for required in (task.spec_path, task.reference_solution_path, task.tests_path):
        if not required.exists():
            raise TaskError(f"task '{task.id}' is missing {required.name}")

    return task
