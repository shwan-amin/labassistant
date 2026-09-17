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

## Using the VS Code extension

1. Start the backend: `uv run labassistant-api` (listens on http://127.0.0.1:8000).
2. Build the extension: `cd vscode-extension && npm install && npm run compile`.
3. Open the `vscode-extension` folder in VS Code and press **F5**. An Extension Development Host window opens with `sample_labs/file_tree`.
4. Open a file such as `metrics.py`, highlight a function, right-click and choose **Lab Assistant: Check my understanding**.
5. The first time, confirm that code may be sent. Then answer the Socratic questions in the side panel.

Concept gaps appear as warnings on the evidence lines; code-quality notes appear as information hints. Settings (backend URL, student id, skip questioning) are under *Settings → Extensions → Lab Assistant*.

## Marker dashboard

Set `MARKER_TOKEN` in `.env`, start the backend, then run `uv run streamlit run ui/streamlit_app.py` and enter the token in the sidebar. The dashboard shows each check's context (included and dropped), token usage, tool calls, rationales and answers, and lets a marker accept, override or reject each concept gap and quality note. Reviews are saved for the evaluation.

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
