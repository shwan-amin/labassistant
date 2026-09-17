# Handoff: Lab Assistant status (2026-09-17)

Read this, then `CLAUDE.md` and `docs/PLAN.md`, before doing anything.

## What the project is

Lab Assistant is a research prototype for a UNSW Taste of Research application ("Agentic AI for Assessment in Experiential Learning Environments"). A student highlights code in VS Code. The system then:

1. builds context from the project;
2. diagnoses concept gaps against an explicit concept graph (recursion), running tests in a sandbox;
3. asks Socratic questions that never reveal the answer;
4. links confirmed gaps to a lecture timestamp and a slide;
5. tracks per-concept mastery.

The author is a 2nd-year UNSW SE student who must be able to explain all the code in an interview. Keep code simple and commented.

## Working rules (from the author)

- **Stages:**
  - Work one stage at a time.
  - At the end of a stage: run tests and lint, tick `docs/PLAN.md`, summarise, and commit locally.
  - **Never push.** The author pushes with `! git push`.
- **Asking vs choosing:**
  - Stop and ask whenever the author's input is needed: choices that affect the evaluation, academic-integrity policy, spending API quota in bulk, or anything only they can do (for example GUI checks).
  - For routine design choices, pick a sensible default and explain it. The author said "do whatever you feel" and "keep working".
- **Secrets:**
  - Never print, log or commit API keys.
  - `.env` is gitignored and holds `GEMINI_API_KEY`, `LLM_MODEL` and `MARKER_TOKEN`.
  - A local pre-commit hook (`.git/hooks/pre-commit`, not versioned) blocks `.env` and key-like strings.
- **Commit attribution:** end commit messages with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Environment and quotas (important)

- **Setup:** Python 3.11 via `uv`; install with `uv sync --extra materials --extra dashboard`. A plain `uv sync` removes the extras.
- **LLM provider:** Gemini **free tier** (`LLM_PROVIDER=gemini`). The code also supports Anthropic (`LLM_PROVIDER=anthropic`), but the author has no Anthropic credits.
- **Free-tier limits, per model** (from the author's dashboard):

  | Model | Requests/min | Requests/day | Notes |
  |---|---|---|---|
  | `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite` | 15 | **500** | `.env` currently sets `LLM_MODEL=gemini-3.5-flash-lite` for rehearsals and bulk work |
  | `gemini-3.6-flash` (code default) and other Flash models | 5 | **20** | Sharper diagnoses |
  | Gemini Embedding | 100 | 1,000 | |
  | Pro models | – | – | Not available |

- **Rate-limit handling:** `GeminiClient` retries per-minute 429s using the delay the API asks for, and raises `DailyQuotaExceededError` on per-day 429s without retrying.
- **Model quality:** on the seeded `count = 1` bug, 3.6-flash found `base_case / base_case_wrong_value` exactly. Flash-Lite said `recursive_decomposition` without an explanation, but found the precise base case gap when the student explanation was given.
- **Request cost:** one extension check with one gap is about 4 requests (diagnosis 2, questions 1, answer 1).
- **Node:** Node 20 via nvm. VS Code 1.138 is installed; `code` is not on PATH (it's at `/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code`).

## Status by stage

| Stage | Status | Notes |
|---|---|---|
| 0 Setup | done | config, LLM interface, fake client with token usage |
| 1 Knowledge + sample labs | done | `knowledge/recursion.json` (7 concepts, 17 misconceptions); `sample_labs/file_tree` and `sample_labs/expression_evaluator` |
| 2 Context builder | done | `src/labassistant/context/`: filtering, ast repo map, relevance, token budget, modes `selection_only`/`file`/`full`, stable/dynamic prompt split for caching |
| 3 Runner | done | `runner/`: sandboxed pytest on a temp copy of the project, probe tests, `run_tests` tool |
| 4 Diagnosis agent | done | `diagnosis/`: tool loop, validation and repair, heuristic leak check, flags `use_tool` / `include_concept_graph`, CLI `labassistant-diagnose` |
| 5 Tutoring + learner model | done | `tutoring/`, `learner/`: one call for all questions, answer judging, SQLite mastery (confirmed → emerging; 2 clears in a row → secure) |
| 6 Teaching material | done | MIT OCW 6.0001 Lecture 6 (CC BY-NC-SA). Media in gitignored `data/raw/`; `materials/mit6_0001_f16_lec6.tags.json` has 21 of 146 entries human-reviewed (one good lecture moment and slide per concept); CLI `labassistant-materials` |
| 7 Backend API | done | `api/`: FastAPI, localhost only, student-safe responses, `labassistant-api` |
| 8 VS Code extension | done | `vscode-extension/`: redesigned panel, concept map removed at the author's request, jump-to-line chips, gaps as warnings, quality notes as hints; `npm test` (32), `npm run test:e2e` (real VS Code + real backend with scripted LLM), `npm run package` → `lab-assistant-0.1.0.vsix` |
| 9 Marker dashboard | done | `ui/streamlit_app.py` plus `/marker/*` endpoints (need `X-Marker-Token`; disabled without `MARKER_TOKEN`); accept/override/reject reviews saved to SQLite |
| 10 Evaluation | **not started** | size decision pending (see below) |
| 11 Write-up | **not started** | |

**Checks at handoff:**
- `uv run pytest`: 270 passed.
- `uv run ruff check .`: clean.
- Extension unit tests: 32 passed.
- End-to-end test: passing.
- Local `main` is 6 commits ahead of `origin/main` (unpushed).

## Key decisions already made (don't re-litigate)

- **Name:** "Lab Assistant", package `labassistant` (renamed from ConceptCoach).
- **Academic integrity:**
  - Gap rationales and answer-judgement rationales are **marker-only**; students see concept name, evidence lines, questions and materials.
  - Misconception ids and probe tests are hidden from students.
  - The leak check can't catch fixes described in words, which is why rationales are marker-only.
- **Questions:** Socratic questions are leak-checked and fall back to a safe template question.
- **"Without concept graph" condition:** the model gets only concept ids and names (no descriptions or misconceptions), so outputs stay scorable.
- **Cost:** estimates return `None` for models without verified prices (no made-up Gemini prices).
- **Teaching material storage:** only links, timestamps, slide numbers and tags are committed. Transcripts, slide text and thumbnails stay local (ShareAlike licence).
- **Extension panel:** has no concept map. The dashboard still shows a graphviz concept graph; the author hasn't said whether to remove that too.

## What the author is doing now

Recording a demo video of the extension, rehearsing on Flash-Lite:

1. Run `uv run labassistant-api`.
2. Install the `.vsix` (or press F5 from `vscode-extension/`).
3. Open `sample_labs/file_tree`, change `count = 0` to `count = 1` in `metrics.py`, and select `count_files` (lines 20–27).
4. Run **Lab Assistant: Check my understanding**, answer the question, and show the lecture and slide cards.

The author may come back with UI feedback from the video. **Remind them to revert `count = 1`**, because the sample lab is committed.

Optional idea, offered but not built: a record/replay LLM mode so retakes cost no requests.

## Next steps

1. **Handle any feedback from the demo recording** (extension UI or behaviour).
2. **Stage 10: Evaluation.** Ask the author which size first:
   - **A (recommended):** about 70 checks (about 200 requests) on `gemini-3.5-flash-lite`. It covers context modes, tool on/off, graph on/off, consistency (3 cases × 3 repeats) and fairness (3 cases × 3 variants). Add a small Flash-Lite vs 3.6-flash comparison on about 5 cases, using one day's 3.6 quota.
   - **B:** manual testing only.
   - **C:** context-mode comparison only.

   Whichever size is chosen:
   - **Dataset:** build it in `eval/dataset/` from the sample labs, with seeded bugs and selection ranges. Allow **multiple acceptable labels** per case: the model reasonably picked `missing_return_on_recursive_call` for a seeded `result_not_combined` bug.
   - **Pacing:** the runner must pace for rate limits, log prompts and usage to `eval/results/logs/`, and support resuming after a daily quota stop.
   - **Retrieval comparison:** tag-based retrieval (`materials/retrieval.py`) vs embeddings (sentence-transformers locally, or Gemini Embedding).
   - **Human ratings:** CSV templates for question quality and retrieval relevance; marker reviews from Stage 9 can feed agreement metrics.
   - **One command:** `uv run python -m eval.run_all` produces the tables and 2–3 charts.
3. **Stage 11: Write-up.**
   - README: research question, Mermaid architecture diagram, extension screenshots or GIF, how to run, evaluation method, results, limitations (small author-labelled dataset, one topic, Python only, free-tier models, heuristic sandbox and leak check), future work.
   - `docs/FINDINGS.md` with 3–4 headline results.

## Useful commands

```bash
uv sync --extra materials --extra dashboard
uv run pytest && uv run ruff check .
uv run labassistant-api                                        # backend, http://127.0.0.1:8000/docs
uv run labassistant-diagnose sample_labs/file_tree metrics.py 20-27 --explanation "..."
uv run labassistant-materials review mit6_0001_f16_lec6
uv run labassistant-materials retrieve base_case
uv run streamlit run ui/streamlit_app.py                       # marker dashboard (token from .env)
cd vscode-extension && npm test && npm run test:e2e && npm run package
```
