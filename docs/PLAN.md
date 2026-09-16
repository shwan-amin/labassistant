# Lab Assistant build plan

One stage at a time, in order. Each stage ends with tests + lint passing, boxes ticked here, a summary and a suggested commit message. Work is committed locally and never pushed.

## Stage 0: Project setup
- [x] Scaffold the repo layout described in `CLAUDE.md`, including `pyproject.toml`, `uv` setup, ruff and pytest config
- [x] Add `.env.example`, `.gitignore` (including `data/raw/` and `.env`), and a skeleton `README.md`
- [x] Add a config module that loads settings from environment variables
- [x] Add a fake LLM client for tests
- **Done when:** `uv run pytest` and `uv run ruff check .` both pass on a placeholder test.

## Stage 1: Knowledge model
- [x] Pydantic schema for the concept graph: concepts with `id`, `name`, `description`, `prerequisites`, and a list of `misconceptions` (each with `id`, `description`, and example symptoms)
- [x] `knowledge/recursion.json` with 6–8 concepts and 2–3 misconceptions each
- [x] Loader with validation: prerequisite IDs exist, no cycles, unique IDs
- [x] One programming task in `tasks/` with a spec, a reference solution and pytest-style test cases
- **Done when:** the graph loads and validates, and tests cover the invalid cases.

## Stage 2: Code execution tool
- [ ] A sandboxed runner that executes a submission against the task's tests, with a timeout, captured output and no network access
- [ ] Returns a structured result: tests passed or failed, error messages, timeouts and exceptions
- [ ] Exposed as an LLM tool definition (`run_tests`)
- **Done when:** tests cover a correct solution, a wrong answer, an infinite recursion or timeout, and a syntax error.

## Stage 3: Diagnosis agent
- [ ] An agent loop that sends the submission, task, concept graph and optional explanation to the LLM, and lets it call `run_tests`
- [ ] Structured output: a list of suspected gaps, each with `concept_id`, `misconception_id` (optional), evidence (line numbers and/or failing tests), and confidence
- [ ] Reject or repair outputs that reference concept IDs not in the graph
- [ ] A flag to switch off the tool and a flag to leave the concept graph out of the prompt (needed for Stage 8)
- **Done when:** unit tests pass with the fake client, and a manual run against the real API on two sample submissions gives sensible output.

## Stage 4: Socratic questioning and learner model
- [ ] Generate one guiding question per suspected gap. The prompt must forbid giving the answer or corrected code.
- [ ] Evaluate the student's reply and mark the gap `confirmed` or `cleared`, with a short rationale
- [ ] Learner model in SQLite: mastery state per student per concept, with a simple, documented update rule that uses both the diagnosis and the answers
- [ ] A session object tying together submission, gaps, questions, answers and updates
- **Done when:** tests cover state transitions, and a scripted role-play session updates mastery sensibly.

## Stage 5: Teaching material retrieval
- [ ] Transcription script: video or audio file → timestamped transcript → chunks of about 30–90 seconds
- [ ] Slide script: PDF → per-slide text and PNG thumbnail
- [ ] LLM-assisted concept tagging for chunks and slides, saved to a reviewable JSON file that can be corrected by hand
- [ ] Retrieval: given a confirmed gap, return the best lecture chunk (with a timestamped link) and the best slide
- [ ] Use openly licensed material or own recording for development. Store links and tags, not rehosted media.
- **Done when:** retrieval returns sensible results for each concept, and the tag file is documented.

## Stage 6: Backend API
- [ ] FastAPI endpoints: create a session and submit code; get the diagnosis and questions; submit an answer; get the learner model and concept map data; get linked materials for a gap
- [ ] Request and response models, error handling, and OpenAPI docs
- **Done when:** API tests pass using FastAPI's test client and the fake LLM.

## Stage 7: Streamlit interface
- [ ] Code input (with a file upload option), optional explanation box, and a "Check my understanding" button
- [ ] A question-and-answer flow, one gap at a time
- [ ] Feedback cards with a slide thumbnail, a clickable lecture timestamp and a short note
- [ ] A concept map showing mastery states, drawn with the graph structure
- [ ] A "marker view" where a human can accept or override each diagnosis
- **Done when:** a full session runs end to end against the real API.

## Stage 8: Evaluation harness
- [ ] `eval/dataset/`: 10–15 submissions labelled with seeded misconceptions (including 2–3 correct controls)
- [ ] Metrics: diagnosis precision/recall; consistency across 5 runs; question-quality CSV template (1–3); retrieval-relevance CSV template
- [ ] Fairness check: renamed variables, comment style, student name header → do diagnoses change?
- [ ] Comparisons: with vs without `run_tests`; with vs without concept graph; tag vs embedding retrieval
- [ ] A script that writes result tables to `eval/results/` and draws 2–3 charts
- **Done when:** one command runs the full evaluation and produces the tables and charts.

## Stage 9: VS Code extension (stretch)
- [ ] TypeScript extension in `vscode-extension/` with a "Lab Assistant: Check my understanding" command
- [ ] Diagnostics highlighting evidence lines for each suspected gap
- [ ] Webview panel for questions, answers, feedback cards and the concept map
- **Done when:** it runs in the Extension Development Host against the local backend.

## Stage 10: Write-up
- [ ] README: research question, Mermaid architecture diagram, how to run, evaluation method, results with charts, limitations, future work
- [ ] `docs/FINDINGS.md` with 3–4 headline results in plain language
- **Done when:** someone new could clone the repo, run the demo and understand the results.
