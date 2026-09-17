import assert from "node:assert/strict";
import { test } from "node:test";
import { escapeHtml, formatTime, isSafeExternalUrl } from "../html";
import { initialPanelState, MaterialWithImage, PanelState, renderPanel } from "../panelHtml";
import { GapStatus, StudentSession } from "../types";

const session = (status: GapStatus): StudentSession => ({
  session_id: "s1",
  selected_path: "metrics.py",
  selection: { start: 20, end: 27 },
  complete: status !== "suspected",
  gaps: [
    {
      index: 0,
      concept_id: "base_case",
      concept_name: "Base case",
      status,
      question: "What does count_files return for an empty directory?",
      evidence: [{ path: "metrics.py", start_line: 24, end_line: 24, test_ids: [] }],
    },
  ],
  quality_notes: [{ category: "other", path: "metrics.py", start_line: 21, end_line: 27, explanation: "<script>alert(1)</script>" }],
});

const materials: MaterialWithImage[] = [
  {
    kind: "lecture",
    source_title: "MIT 6.0001 Lecture 6: Recursion and Dictionaries",
    note: "long note that the panel no longer shows",
    url: "https://archive.org/v.mp4#t=511",
    start_seconds: 511,
    end_seconds: 554,
    slide_number: null,
    thumbnail_url: null,
    attribution: "MIT OCW, CC BY-NC-SA",
  },
  {
    kind: "slide",
    source_title: "MIT 6.0001 Lecture 6: Recursion and Dictionaries",
    note: "",
    url: "https://ocw.mit.edu/slides.pdf",
    start_seconds: null,
    end_seconds: null,
    slide_number: 10,
    thumbnail_url: "/t",
    thumbnailDataUri: "data:image/png;base64,AAAA",
    attribution: "MIT OCW, CC BY-NC-SA",
  },
];

const ready = (overrides: Partial<PanelState>): PanelState => ({ ...initialPanelState(), status: "ready", ...overrides });

test("question state: question, answer form and clickable evidence line", () => {
  const html = renderPanel(
    ready({ session: session("suspected"), nextQuestion: { gap_index: 0, concept_name: "Base case", question: 'What does "count" start at?' } }),
    "abc123",
  );
  assert.ok(html.includes("script-src 'nonce-abc123'") && html.includes("default-src 'none'"));
  assert.ok(html.includes('<blockquote class="question">What does &quot;count&quot; start at?</blockquote>'));
  assert.ok(html.includes('id="answer-form" data-gap="0"'));
  assert.ok(html.includes('data-path="metrics.py" data-line="24"'));
  assert.ok(html.includes("metrics.py · line 24"));
});

test("feedback state: answer, outcome, level change and learn-more cards", () => {
  const html = renderPanel(
    ready({
      session: session("confirmed"),
      answers: { 0: "It returns one." },
      lastChange: { concept_id: "base_case", old_state: "unknown", new_state: "emerging" },
      materials: { 0: materials },
    }),
    "n",
  );
  assert.ok(html.includes("Your answer") && html.includes("It returns one."));
  assert.ok(html.includes("Worth revisiting") && html.includes("worth another look"));
  assert.ok(html.includes("Base case level: unknown") && html.includes("<b>emerging</b>"));
  assert.ok(html.includes("Watch 8:31–9:14") && html.includes('data-url="https://archive.org/v.mp4#t=511"'));
  assert.ok(html.includes('<img src="data:image/png;base64,AAAA" alt="Slide 10">') && html.includes("Slide 10"));
  assert.ok(!html.includes("long note that the panel no longer shows"));
  assert.equal(html.split("MIT OCW, CC BY-NC-SA").length - 1, 1); // attribution shown once, in the footer
  assert.ok(!html.includes("id=\"answer-form\""));
});

test("cleared gap is shown as understood without materials", () => {
  const html = renderPanel(ready({ session: session("cleared"), answers: { 0: "Zero." } }), "n");
  assert.ok(html.includes("Understood") && html.includes("You explained this well."));
  assert.ok(!html.includes("Learn more"));
});

test("quality notes are escaped and collapsed", () => {
  const html = renderPanel(ready({ session: session("confirmed") }), "n");
  assert.ok(html.includes("<details class=\"notes\"><summary>Code quality notes (1)</summary>"));
  assert.ok(!html.includes("<script>alert(1)</script>") && html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(html.includes("<b>Note</b>")); // "other" shows as a neutral label
});

test("no concept map is rendered", () => {
  const html = renderPanel(ready({ session: session("confirmed"), materials: { 0: materials } }), "n");
  assert.ok(!html.toLowerCase().includes("concept map"));
  assert.ok(!html.includes("<rect"));
});

test("loading, error, answering and empty states", () => {
  assert.ok(renderPanel({ ...initialPanelState(), status: "loading", message: "Checking..." }, "n").includes("Checking..."));
  assert.ok(renderPanel({ ...initialPanelState(), status: "error", message: "Backend down" }, "n").includes('role="alert"'));
  const answering = renderPanel(
    ready({
      session: session("suspected"),
      nextQuestion: { gap_index: 0, concept_name: "Base case", question: "Q?" },
      answers: { 0: "my answer" },
      answering: true,
    }),
    "n",
  );
  assert.ok(answering.includes("Checking your answer...") && answering.includes("my answer"));
  assert.ok(!answering.includes('id="answer-form"'));
  const noGaps = renderPanel(ready({ session: { ...session("suspected"), gaps: [] } }), "n");
  assert.ok(noGaps.includes("No concept gaps found"));
});

test("html helpers", () => {
  assert.equal(escapeHtml(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.deepEqual([formatTime(59.9), formatTime(511), formatTime(3725)], ["0:59", "8:31", "1:02:05"]);
  assert.ok(isSafeExternalUrl("https://ocw.mit.edu/x"));
  assert.ok(!isSafeExternalUrl("javascript:alert(1)") && !isSafeExternalUrl("file:///etc/passwd") && !isSafeExternalUrl("nope"));
});
