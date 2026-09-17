import assert from "node:assert/strict";
import { test } from "node:test";
import { diagnosticsFor } from "../diagnostics";
import { StudentSession } from "../types";

const session = (status: "suspected" | "cleared"): StudentSession => ({
  session_id: "s",
  selected_path: "metrics.py",
  selection: { start: 20, end: 27 },
  complete: false,
  gaps: [
    {
      index: 0,
      concept_id: "base_case",
      concept_name: "Base case",
      status,
      question: "What happens for an empty directory?",
      evidence: [{ path: "metrics.py", start_line: 24, end_line: 24, test_ids: [] }],
    },
  ],
  quality_notes: [
    { category: "error_handling", path: "loader.py", start_line: 3, end_line: 5, explanation: "Invalid specs are not reported." },
  ],
});

test("gaps and quality notes become different kinds of diagnostics", () => {
  const specs = diagnosticsFor(session("suspected"));
  assert.deepEqual(specs, [
    {
      path: "metrics.py",
      startLine: 24,
      endLine: 24,
      message: "Possible gap in Base case: answer the question in the Lab Assistant panel.",
      kind: "concept-gap",
    },
    {
      path: "loader.py",
      startLine: 3,
      endLine: 5,
      message: "Error handling: Invalid specs are not reported.",
      kind: "quality-note",
    },
  ]);
});

test("cleared gaps are no longer highlighted, and the question is not put in the editor", () => {
  const specs = diagnosticsFor(session("cleared"));
  assert.deepEqual(specs.map((s) => s.kind), ["quality-note"]);
  assert.ok(diagnosticsFor(session("suspected")).every((s) => !s.message.includes("empty directory")));
});

test("'other' quality notes have no category prefix", () => {
  const specs = diagnosticsFor({
    ...session("suspected"),
    gaps: [],
    quality_notes: [{ category: "other", path: "a.py", start_line: 1, end_line: 1, explanation: "Docstring and code disagree." }],
  });
  assert.equal(specs[0].message, "Docstring and code disagree.");
});
