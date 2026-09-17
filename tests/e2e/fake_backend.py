"""A real Lab Assistant backend whose LLM is scripted, for the VS Code end-to-end test.

    uv run python -m tests.e2e.fake_backend --port 8799 --project /path/to/seeded/file_tree

Everything is real (FastAPI, context builder, sandboxed test runs, retrieval,
learner store) except the model's replies, so the extension test is repeatable
and needs no API key.
"""

import argparse
import json
import tempfile
from pathlib import Path

import uvicorn

from labassistant.api.app import create_app
from labassistant.config import Settings
from labassistant.llm import FakeLLMClient

ROOT = Path(__file__).resolve().parents[2]
FAILING_TEST = "tests/test_metrics.py::test_count_files_ignores_directories"


def scripted_client(bug_line: int) -> FakeLLMClient:
    gap = {
        "concept_id": "base_case",
        "misconception_id": "base_case_wrong_value",
        "confidence": "high",
        "evidence": [
            {
                "path": "metrics.py",
                "start_line": bug_line,
                "end_line": bug_line,
                "test_ids": [FAILING_TEST],
            }
        ],
        "rationale": "Scripted marker-only rationale.",
    }
    note = {
        "category": "readability",
        "path": "metrics.py",
        "start_line": bug_line,
        "end_line": bug_line,
        "explanation": "A short comment on what the starting count represents would help readers.",
    }
    return FakeLLMClient(
        [
            FakeLLMClient.tool_use(
                "run_tests", {"test_ids": [FAILING_TEST]}
            ),  # runs the real sandbox
            FakeLLMClient.text(json.dumps({"concept_gaps": [gap], "quality_notes": [note]})),
            FakeLLMClient.text(
                json.dumps(
                    {
                        "questions": [
                            {
                                "gap_index": 0,
                                "question": (
                                    "If count_files is called on an empty directory, what value "
                                    f"does line {bug_line} start with, and what is returned?"
                                ),
                            }
                        ]
                    }
                )
            ),
            FakeLLMClient.text(
                json.dumps({"verdict": "confirmed", "rationale": "Scripted judgement."})
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument(
        "--project", type=Path, required=True, help="seeded project, to find the bug line"
    )
    args = parser.parse_args()

    lines = (args.project / "metrics.py").read_text().splitlines()
    bug_line = next(i for i, line in enumerate(lines, start=1) if "count = 1" in line)
    settings = Settings(
        _env_file=None,
        database_path=Path(tempfile.mkdtemp()) / "e2e.db",
        knowledge_dir=ROOT / "knowledge",
        materials_dir=ROOT / "materials",
        processed_materials_dir=ROOT / "data" / "raw" / "processed",
    )
    uvicorn.run(
        create_app(settings, client=scripted_client(bug_line)),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
