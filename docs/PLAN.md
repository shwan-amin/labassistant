# Lab Assistant build plan

One stage at a time, in order. Each stage ends with tests + lint passing, boxes ticked here, a summary and a suggested commit message. Work is committed locally and never pushed.

> **Plan revised** after Stages 0–2 of the original plan were built. The main interface is now a VS Code extension working on a highlighted selection in a multi-file project, with a context builder and an academic-integrity check. The original single-task runner was reworked into the project runner in Stage 3, and `tasks/sum_nested` was replaced by `sample_labs/`. After Stage 3, a Gemini adapter was added (`LLM_PROVIDER=gemini`, the default) so development and evaluation can use a free-tier key; the Anthropic client remains available.

## Stage 0: Project setup
- [x] Scaffold the repo layout described in `CLAUDE.md`, including `pyproject.toml`, `uv` setup, ruff and pytest config
- [x] Add `.env.example`, `.gitignore` (including `data/raw/` and `.env`), and a skeleton `README.md`
- [x] Add a config module that loads settings from environment variables, including the context token budget
- [x] Add a fake LLM client for tests that also reports fake token usage
- **Done when:** `uv run pytest` and `uv run ruff check .` both pass on a placeholder test.

## Stage 1: Knowledge model and sample labs
- [x] Pydantic schema for the concept graph: concepts with `id`, `name`, `description`, `prerequisites`, and a list of `misconceptions` (each with `id`, `description`, and example symptoms)
- [x] `knowledge/recursion.json` with 6–8 concepts and 2–3 misconceptions each
- [x] Loader with validation: prerequisite IDs exist, no cycles, unique IDs
- [x] 2 small sample lab projects in `sample_labs/` (3–6 Python files each, with a short spec and a few pytest tests) that use recursion across more than one file
- **Done when:** the graph loads and validates, tests cover the invalid cases, and the sample labs' own tests pass on their reference versions.

## Stage 2: Context builder
- [x] Input model: project files (path and content), selected file path, and selection line range
- [x] Filtering: skip gitignored, binary, generated and oversized files, and cap the total project size
- [x] Extract the selection and its enclosing function or class
- [x] Repo map with `ast`: per file, imports, function and class signatures, and docstrings
- [x] Relevance: find project functions and modules the selection calls or imports, and include those in full
- [x] Token budget: fill in priority order (selection → enclosing function → rest of file → directly used code → repo map → spec) and record what was included or dropped
- [x] A context mode setting (`selection_only`, `file`, `full`) for the evaluation comparison
- [x] Order the prompt so the stable part (repo map, spec) can be cached across repeat checks
- **Done when:** tests cover selection extraction, relevance detection, budget truncation, each context mode, and non-parseable files.

## Stage 3: Code execution tool
- [x] A sandboxed runner that copies the project to a temp directory and runs either the project's existing tests or agent-written probe tests, with a timeout, captured output and no network access
- [x] Returns a structured result: tests passed or failed, error messages, timeouts and exceptions
- [x] Exposed as an LLM tool definition (`run_tests`) that takes optional probe test code
- [x] Probe tests are for diagnosis only and are never shown to the student as code to copy
- **Done when:** tests cover a correct project, a wrong answer, an infinite recursion or timeout, a syntax error, and a probe test.

## Stage 4: Diagnosis agent
- [x] An agent loop that sends the built context, concept graph and optional explanation to the LLM, and lets it call `run_tests`
- [x] Structured output with two lists:
  - concept gaps: `concept_id`, `misconception_id` (optional), evidence (file and line numbers, failing tests), and confidence
  - quality notes: category, file and line numbers, and a short explanation with no corrected code
- [x] Reject or repair outputs that reference concept IDs not in the graph, or line numbers outside the project files
- [x] A post-check that flags and removes any output that contains solution code
- [x] Flags to switch off the tool and to leave the concept graph out of the prompt (needed for evaluation)
- [x] Record token usage and cost estimate per check
- **Done when:** unit tests pass with the fake client, and a manual run against the real API on both sample labs gives sensible output.

## Stage 5: Socratic questioning and learner model
- [x] Generate one guiding question per concept gap. The prompt must forbid giving the answer or corrected code.
- [x] Evaluate the student's reply and mark the gap `confirmed` or `cleared`, with a short rationale
- [x] Learner model in SQLite: mastery state per student per concept, with a simple, documented update rule that uses both the diagnosis and the answers
- [x] A session object tying together selection, context summary, gaps, quality notes, questions, answers and updates
- [x] A setting to skip questioning and show feedback directly
- **Done when:** tests cover state transitions, and a scripted role-play session updates mastery sensibly.

## Stage 6: Teaching material retrieval
- [x] Transcription script: video or audio file → timestamped transcript → chunks of about 30–90 seconds
- [x] Slide script: PDF → per-slide text and PNG thumbnail
- [x] LLM-assisted concept tagging for chunks and slides, saved to a reviewable JSON file that can be corrected by hand
- [x] Retrieval: given a confirmed concept gap, return the best lecture chunk (with a timestamped link) and the best slide
- [x] Use openly licensed material or own recording for development. Store links and tags, not rehosted media.
- **Done when:** retrieval returns sensible results for each concept, and the tag file is documented.

## Stage 7: Backend API
- [x] FastAPI endpoints: start a check (project files, selected file, line range, optional explanation); get diagnosis, quality notes and questions; submit an answer; get the learner model and concept map data; get linked materials for a gap; serve slide thumbnails
- [x] Request size limits, request and response models, error handling, and OpenAPI docs
- [x] Runs locally on `localhost` only
- **Done when:** API tests pass using FastAPI's test client and the fake LLM.

## Stage 8: VS Code extension (main interface)
- [x] TypeScript extension in `vscode-extension/` with a "Lab Assistant: Check my understanding" command, available from the right-click menu when text is selected
- [x] Collect the selection, its file and line range, and workspace files (respecting `.gitignore` and size limits), with an optional explanation input box
- [x] A one-time consent prompt explaining that code is sent to an external LLM API, plus a setting for the backend URL
- [x] Show concept gaps and quality notes as diagnostics on the evidence lines, with different severity or styling for each kind
- [x] A webview side panel for Socratic questions and answers, feedback cards with slide thumbnails and clickable lecture timestamps, and the concept map
- [x] Clear loading and error states (backend not running, request too large, API failure)
- **Done when:** a full session can be completed by highlighting code in a sample lab in the Extension Development Host, against the local backend and real API. *(Pending: manual check by the author in the Extension Development Host.)*

## Stage 9: Streamlit dev and marker dashboard
- [ ] Load a saved session and view the built context, including what was included and dropped, plus token usage
- [ ] A "marker view" where a human can accept or override each concept gap and quality note (human–AI interaction), with overrides saved for evaluation
- [ ] A learner model viewer
- **Done when:** sessions created from the extension can be inspected and reviewed.

## Stage 10: Evaluation harness (the research part)
- [ ] `eval/dataset/`: 10–15 cases built from the sample labs, each with a chosen selection range and labelled with the misconceptions deliberately seeded into it (including 2–3 correct selections as controls)
- [ ] Metrics: concept gap precision and recall; consistency across 5 repeated runs; question-quality CSV template (1–3, "guides without revealing"); retrieval-relevance CSV template; count of solution-code leaks caught by the post-check
- [ ] Fairness check: rename variables, change comment style and add a student name header, then measure whether diagnoses change
- [ ] Comparisons:
  - context mode: `selection_only` vs `file` vs `full`, reporting accuracy against tokens and estimated cost
  - with vs without the `run_tests` tool
  - with vs without the concept graph in the prompt
  - concept-tag retrieval vs embedding retrieval
- [ ] A script that writes result tables to `eval/results/` and draws 2–3 clear charts, including accuracy vs cost by context mode
- **Done when:** one command runs the full evaluation and produces the tables and charts.

## Stage 11: Write-up
- [ ] README: research question, Mermaid architecture diagram, screenshots or GIF of the extension, how to run, evaluation method, results with charts, limitations (small dataset, single topic, Python only, author-labelled data), future work (more topics and languages, real course material with permission, user studies)
- [ ] `docs/FINDINGS.md` with 3–4 headline results in plain language
- **Done when:** someone new could clone the repo, run the demo and understand the results.
