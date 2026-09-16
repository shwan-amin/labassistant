"""Run one diagnosis from the command line, against the configured real LLM.

    uv run labassistant-diagnose sample_labs/file_tree metrics.py 20-27 \\
        --explanation "Counts files recursively"

Prints the diagnosis as JSON (probe test code is left out). Uses your API key.
"""

import argparse
import json
import sys
from pathlib import Path

from labassistant.config import get_settings
from labassistant.context.filtering import DEFAULT_IGNORED_DIRS
from labassistant.context.models import ContextRequest, LineRange, ProjectFile
from labassistant.diagnosis.agent import DiagnosisAgent, DiagnosisError
from labassistant.diagnosis.models import DiagnosisOptions
from labassistant.knowledge.loader import load_topic
from labassistant.llm.factory import create_llm_client


def read_project(root: Path) -> list[ProjectFile]:
    """Read text files under `root`; the context builder applies the real filtering."""
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in DEFAULT_IGNORED_DIRS for part in relative.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary file
        files.append(ProjectFile(path=relative.as_posix(), content=content))
    return files


def parse_lines(text: str) -> LineRange:
    start, _, end = text.partition("-")
    return LineRange(start=int(start), end=int(end or start))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("project", type=Path, help="project folder")
    parser.add_argument("file", help="selected file, relative to the project")
    parser.add_argument("lines", type=parse_lines, help="selected lines, e.g. 12-20")
    parser.add_argument("--explanation", default=None)
    parser.add_argument("--topic", default="recursion")
    parser.add_argument("--no-tool", action="store_true", help="disable run_tests")
    parser.add_argument("--no-graph", action="store_true", help="leave the concept graph out")
    args = parser.parse_args(argv)

    settings = get_settings()
    agent = DiagnosisAgent(
        create_llm_client(settings),
        load_topic(args.topic, settings.knowledge_dir),
        model_name=settings.model_name,
        context_mode=settings.context_mode,
        token_budget=settings.context_token_budget,
        runner_timeout_seconds=settings.runner_timeout_seconds,
    )
    request = ContextRequest(
        files=read_project(args.project),
        selected_path=args.file,
        selection=args.lines,
        explanation=args.explanation,
    )
    options = DiagnosisOptions(use_tool=not args.no_tool, include_concept_graph=not args.no_graph)
    try:
        result = agent.diagnose(request, options)
    except DiagnosisError as exc:
        print(f"diagnosis failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            result.model_dump(mode="json", exclude={"tool_calls": {"__all__": {"probe_code"}}}),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
