# Lab Assistant

An agentic Socratic tutor used from inside VS Code. A student highlights code in their lab or assignment, and Lab Assistant assesses their *understanding* of core computing concepts instead of giving a mark. It builds context from the wider codebase, diagnoses concept gaps using an explicit concept graph, adds separate general code-quality notes, probes gaps with guiding questions, links feedback to lecture timestamps and slides, and tracks a per-concept learner model. It is a research prototype for a UNSW Taste of Research application ("Agentic AI for Assessment in Experiential Learning Environments").

## Progress

The staged plan lives in `docs/PLAN.md`. Always check it before starting work. The latest status, quotas and open decisions are in `docs/HANDOFF.md`.

- Work on one stage at a time, in order.
- At the end of a stage: run tests and lint, tick the completed boxes in `docs/PLAN.md`, summarise what changed, and suggest a commit message.
- **Do not start the next stage until the user says so.**
- Stop and ask whenever the user's input is needed (design choices, content, anything affecting evaluation).

## Architecture

The concept graph is the backbone. Concept gaps, questions, lecture chunks and slides all refer to its concept IDs.

```
VS Code extension (selection + project files)
        │
        ▼
FastAPI backend
        │
        ▼
context builder ── selection → enclosing function → file → directly used code → repo map → spec
        │            (token budget, cache-friendly ordering)
        ▼
diagnosis agent ──(run_tests tool: project tests or probe tests)──> sandboxed runner
        │
        ├── concept gaps (concept_id, evidence, confidence)
        │         │
        │         ▼
        │   Socratic questions ──> student answers ──> learner model (SQLite)
        │         │
        │         ▼
        │   confirmed gaps ──> retrieval ──> lecture chunk (timestamp) + slide (thumbnail)
        │
        └── quality notes (general good practice, not linked to concepts)
        │
        ▼
extension shows line highlights + side panel
```

Interfaces (VS Code extension, Streamlit dashboard) only talk to the FastAPI backend. No core logic belongs in a UI. `/marker/*` endpoints expose marker-only data (rationales, answer judgements, probe code) and require the `X-Marker-Token` header; they are disabled when `MARKER_TOKEN` is unset.

## Repo layout

```
src/labassistant/
  config.py          # settings from environment variables
  llm/               # LLM client interface, Anthropic client, fake client for tests
  knowledge/         # concept graph schema and loader
  context/           # file filtering, selection extraction, repo map, relevance, token budget
  runner/            # sandboxed execution + run_tests tool definition
  diagnosis/         # diagnosis agent, output validation, solution-leak check
  tutoring/          # Socratic question generation and answer evaluation
  learner/           # learner model and persistence
  materials/         # transcription, slide extraction, tagging, retrieval
  api/               # FastAPI app
knowledge/           # concept graph JSON files (e.g. recursion.json)
sample_labs/         # small multi-file Python lab projects for development and evaluation
materials/           # concept tag files for lecture chunks and slides (no media)
data/raw/            # local recordings and slide PDFs, gitignored
vscode-extension/    # main interface (TypeScript)
ui/streamlit_app.py  # dev and marker dashboard
eval/                # dataset, evaluation scripts, results
tests/
docs/                # PLAN.md, FINDINGS.md
```

## Commands

```bash
uv sync --extra materials --extra dashboard      # install dependencies (plain `uv sync` removes the extras)
uv run pytest                                    # run tests (offline, fake LLM)
uv run ruff check . && uv run ruff format .      # lint and format
uv run labassistant-api                          # backend on http://127.0.0.1:8000 (docs at /docs)
uv run streamlit run ui/streamlit_app.py         # marker dashboard (needs MARKER_TOKEN on the backend)
uv run python -m eval.run_all                    # full evaluation
uv run labassistant-diagnose sample_labs/file_tree metrics.py 20-27   # one real diagnosis (uses your API key)
uv run labassistant-materials review mit6_0001_f16_lec6            # check lecture/slide concept tags (see materials/README.md)

cd vscode-extension && npm install && npm run compile && npm test
npm run test:e2e        # real VS Code + real backend with a scripted LLM (downloads VS Code once)
npm run package         # builds lab-assistant-<version>.vsix
# then press F5 in VS Code to open the Extension Development Host
```

Update this section if commands change.

## Conventions

- Python 3.11+, type hints everywhere, Pydantic v2 models for all structured data crossing module boundaries.
- TypeScript in strict mode for the extension.
- Keep code readable and well named. The author must be able to explain every part in an interview, so prefer simple, explicit code and add brief comments on non-obvious design choices.
- Small functions, small modules. No core logic in UI code.
- Every stage adds tests. Tests must not touch the network: use the fake LLM client.
- Line numbers are 1-based and always paired with a file path.

## Git

- Commit completed work locally, but **never push**. The author pushes.

## Context and cost

- Never send the whole codebase blindly. Build context in priority order within the configured token budget, and record what was included and dropped.
- Put stable content (repo map, spec, concept graph) before the changing selection so prompt caching can reuse it.
- Only Python projects are parsed for the repo map for now. Other files are included as plain text if they fit, or skipped.
- Record input, output and cached tokens for every LLM call.

## LLM usage

- All LLM calls go through the client interface in `src/labassistant/llm/`. Create clients with `create_llm_client()`.
- Provider comes from `LLM_PROVIDER`: `gemini` (default, used for development and evaluation on the free tier) or `anthropic`. Keys come from `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`, and the model from `LLM_MODEL` (defaults: `gemini-3.6-flash`, `claude-sonnet-5`). Never hard-code keys or model names.
- Messages use the Anthropic content-block format internally; provider adapters translate. Always append a response's `content` blocks unchanged (they carry Gemini thought signatures).
- Ask for structured JSON output and validate it with Pydantic. On invalid output, retry once with the validation error, then fail clearly.
- Any concept or misconception ID from the model must exist in the loaded concept graph. Any file and line reference must exist in the submitted project.
- Keep concept gaps and quality notes separate. Only concept gaps are linked to the concept graph and teaching material.
- Keep prompts in their own files or constants so they are easy to compare in experiments.
- The Gemini free tier allows about 5 requests per minute per model. The Gemini client waits and retries on 429s; batch runs (evaluation) must pace themselves.
- Log prompts, responses and token usage for evaluation runs to `eval/results/logs/`.

## Academic integrity (hard rule)

Students use this on assessed work. The system must **never** produce solutions, corrected code, or code a student could paste in as an answer. It may point to lines, ask guiding questions and explain concepts in general terms. Probe tests written by the agent are for diagnosis only and are never shown to the student. Every student-facing output passes the solution-leak check before it is returned. Concept gap **rationales are for markers only**: students see evidence lines, Socratic questions and teaching material, never the rationale (it can describe the fix in words, which no regex can reliably catch).

## Safety and data rules

- Student code is untrusted. Only run it through `runner/`, in a subprocess in a temporary copy of the project, with a timeout and no network access. Never `exec` or `eval` it in the main process.
- The extension asks for consent before sending code to the external LLM API, and the backend listens on `localhost` only.
- Never commit `.env`, API keys, lecture recordings, slide PDFs, other course material, or real assignment code. `data/raw/` stays gitignored.
- Never print, log or echo API keys. A local pre-commit hook (`.git/hooks/pre-commit`, not versioned) blocks commits containing `.env` or key-like strings.
- For development, use openly licensed material or the author's own recordings. Store links and tags, not rehosted media, and credit sources in the README.
- Don't use real student work. Evaluation cases come from `sample_labs/`, written or generated by the author and labelled with seeded misconceptions.

## Evaluation (the research part)

The goal is measured claims, not just a demo. Key comparisons:

- context mode: selection only vs whole file vs selection plus codebase map (accuracy against tokens and cost)
- diagnosis with vs without the `run_tests` tool
- diagnosis with vs without the concept graph in the prompt
- concept-tag retrieval vs embedding retrieval

Metrics: concept gap precision and recall against seeded labels, consistency over repeated runs, fairness under changes that shouldn't matter (variable names, comment style, name headers), solution leaks caught, and human-rated question quality and retrieval relevance. Report limitations honestly.

## When unsure

Ask rather than guess, especially about scope, design trade-offs, academic integrity, or anything that would change the evaluation.
