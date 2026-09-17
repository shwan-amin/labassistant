# Lab Assistant

An agentic Socratic tutor used from inside VS Code. A student highlights code in their lab, and Lab Assistant assesses their *understanding* of core computing concepts rather than giving a mark. It never writes solutions or corrected code.

> Research prototype for the UNSW Taste of Research project "Agentic AI for Assessment in Experiential Learning Environments". Work in progress: see [`docs/PLAN.md`](docs/PLAN.md).

## Research question

_To be written (Stage 10)._

## Architecture

_Mermaid diagram to be added (Stage 10)._

## Getting started

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # then add GEMINI_API_KEY (or set LLM_PROVIDER=anthropic)
uv run pytest
uv run ruff check .
uv run labassistant-api   # backend on http://127.0.0.1:8000, interactive API docs at /docs
```

## Evaluation

_To be written (Stage 8)._

## Results

_To be written (Stage 10)._

## Limitations

_To be written (Stage 10)._

## Future work

_To be written (Stage 10)._

## Credits

Teaching material links and concept tags (not the media itself) refer to:

- **MIT 6.0001 Lecture 6: Recursion and Dictionaries** (video and slides). Eric Grimson, John Guttag, and Ana Bell. *6.0001 Introduction to Computer Science and Programming in Python*, Fall 2016. Massachusetts Institute of Technology: [MIT OpenCourseWare](https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/). License: [Creative Commons BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The lecture and slides are not redistributed in this repository; `materials/mit6_0001_f16_lec6.tags.json` contains only timestamps, slide numbers and concept tags derived from them, shared under the same licence.
