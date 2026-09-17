import assert from "node:assert/strict";
import { test } from "node:test";
import { layout, levels, renderConceptMapSvg } from "../conceptMap";
import { escapeHtml, formatTime, isSafeExternalUrl } from "../html";
import { initialPanelState, PanelState, renderPanel } from "../panelHtml";
import { ConceptMap, StudentSession } from "../types";

const map: ConceptMap = {
  student_id: "s",
  topic: "recursion",
  nodes: [
    { id: "decomp", name: "Recursive decomposition", description: "", state: "secure", prerequisites: [] },
    { id: "base", name: "Base case", description: "", state: "emerging", prerequisites: ["decomp"] },
    { id: "rec", name: "Recursive case", description: "", state: "unknown", prerequisites: ["decomp"] },
    { id: "progress", name: "Progress", description: "", state: "unknown", prerequisites: ["base", "rec"] },
  ],
  edges: [
    { source: "decomp", target: "base" },
    { source: "decomp", target: "rec" },
    { source: "base", target: "progress" },
    { source: "rec", target: "progress" },
  ],
};

const session: StudentSession = {
  session_id: "s1",
  selected_path: "metrics.py",
  selection: { start: 20, end: 27 },
  complete: false,
  gaps: [
    {
      index: 0,
      concept_id: "base",
      concept_name: "Base case",
      status: "confirmed",
      question: null,
      evidence: [{ path: "metrics.py", start_line: 24, end_line: 24, test_ids: [] }],
    },
  ],
  quality_notes: [{ category: "naming", path: "metrics.py", start_line: 21, end_line: 21, explanation: "<script>alert(1)</script>" }],
};

test("concept levels follow prerequisites", () => {
  assert.deepEqual(Object.fromEntries(levels(map)), { decomp: 0, base: 1, rec: 1, progress: 2 });
  const { nodes } = layout(map);
  const y = Object.fromEntries(nodes.map((n) => [n.id, n.y]));
  assert.ok(y.decomp < y.base && y.base === y.rec && y.rec < y.progress);
});

test("concept map SVG has a coloured node per concept and an edge per prerequisite", () => {
  const svg = renderConceptMapSvg(map);
  assert.equal((svg.match(/<rect /g) ?? []).length, 4);
  assert.equal((svg.match(/<line /g) ?? []).length, 4);
  assert.ok(svg.includes('class="node secure"') && svg.includes("#2e9e4f"));
});

test("cyclic data does not hang the layout", () => {
  const cyclic: ConceptMap = { ...map, nodes: [{ ...map.nodes[0], prerequisites: ["base"] }, ...map.nodes.slice(1)] };
  assert.equal(levels(cyclic).size, 4);
});

test("panel escapes text and uses a nonce-based CSP", () => {
  const state: PanelState = {
    ...initialPanelState(),
    status: "ready",
    session,
    nextQuestion: { gap_index: 0, concept_name: "Base case", question: 'What does "count" start at?' },
    materials: {
      0: [
        {
          kind: "lecture",
          source_title: "Lecture",
          note: "Watch 8:31-9:14",
          url: "https://archive.org/v.mp4#t=511",
          start_seconds: 511,
          end_seconds: 554,
          slide_number: null,
          thumbnail_url: null,
          attribution: "MIT OCW",
        },
      ],
    },
    conceptMap: map,
  };
  const html = renderPanel(state, "abc123");

  assert.ok(html.includes("script-src 'nonce-abc123'") && html.includes("default-src 'none'"));
  assert.ok(!html.includes("<script>alert(1)</script>"));
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(html.includes("What does &quot;count&quot; start at?"));
  assert.ok(html.includes('data-url="https://archive.org/v.mp4#t=511"') && html.includes("Watch from 8:31"));
  assert.ok(html.includes('id="answer-form" data-gap="0"'));
  assert.ok(html.includes("<svg"));
});

test("loading, error and answering states", () => {
  assert.ok(renderPanel({ ...initialPanelState(), status: "loading", message: "Checking..." }, "n").includes("Checking..."));
  assert.ok(renderPanel({ ...initialPanelState(), status: "error", message: "Backend down" }, "n").includes('role="alert"'));
  const answering = renderPanel(
    { ...initialPanelState(), status: "ready", session, nextQuestion: { gap_index: 0, concept_name: "B", question: "Q?" }, answering: true },
    "n",
  );
  assert.ok(answering.includes("Checking your answer...") && answering.includes("disabled"));
  const noGaps = renderPanel({ ...initialPanelState(), status: "ready", session: { ...session, gaps: [] } }, "n");
  assert.ok(noGaps.includes("No concept gaps found"));
});

test("html helpers", () => {
  assert.equal(escapeHtml(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.deepEqual([formatTime(59.9), formatTime(511), formatTime(3725)], ["0:59", "8:31", "1:02:05"]);
  assert.ok(isSafeExternalUrl("https://ocw.mit.edu/x"));
  assert.ok(!isSafeExternalUrl("javascript:alert(1)") && !isSafeExternalUrl("file:///etc/passwd") && !isSafeExternalUrl("nope"));
});
