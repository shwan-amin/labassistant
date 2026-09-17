// Runs inside the VS Code extension host started by runTest.ts.

import assert from "node:assert/strict";
import * as vscode from "vscode";
import type { LabAssistantTestApi } from "../extension";
import type { PanelState } from "../panelHtml";

const REAL_LLM = process.env.E2E_REAL_LLM === "1";

async function waitFor(what: string, condition: () => boolean, seconds: number): Promise<void> {
  for (let i = 0; i < seconds * 4; i++) {
    if (condition()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`timed out waiting for ${what}`);
}

function log(message: string): void {
  console.log(`[e2e] ${message}`);
}

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension<LabAssistantTestApi>("labassistant-research.lab-assistant");
  assert.ok(extension, "extension is installed in the test host");
  const api = await extension.activate();

  const folder = vscode.workspace.workspaceFolders?.[0];
  assert.ok(folder, "sample lab is open");
  await vscode.workspace
    .getConfiguration("labAssistant")
    .update("backendUrl", process.env.E2E_BACKEND_URL, vscode.ConfigurationTarget.Global);
  await vscode.workspace.getConfiguration("labAssistant").update("studentId", "e2e-student", vscode.ConfigurationTarget.Global);
  await api.setConsent(true);

  // Open metrics.py and select count_files, as a student would.
  const uri = vscode.Uri.joinPath(folder.uri, "metrics.py");
  const document = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(document);
  const lines = document.getText().split("\n");
  const start = lines.findIndex((line) => line.startsWith("def count_files"));
  const end = lines.findIndex((line, i) => i > start && line.includes("return count"));
  editor.selection = new vscode.Selection(start, 0, end, lines[end].length);
  const bugLine = lines.findIndex((line) => line.includes("count = 1")) + 1;
  log(`selected metrics.py lines ${start + 1}-${end + 1}; seeded bug on line ${bugLine}`);

  await vscode.commands.executeCommand("labAssistant.checkUnderstanding", { explanation: "Counts the files in the tree recursively." });
  await waitFor("the check to finish", () => api.state().status !== "loading", REAL_LLM ? 300 : 90);
  const checked: PanelState = api.state();
  assert.equal(checked.status, "ready", `check failed: ${checked.message}`);
  const session = checked.session!;
  log(`gaps: ${JSON.stringify(session.gaps.map((g) => [g.concept_name, g.status, g.evidence.map((e) => `${e.path}:${e.start_line}`)]))}`);
  log(`quality notes: ${session.quality_notes.length}; question: ${checked.nextQuestion?.question}`);

  if (!REAL_LLM) {
    // Deterministic expectations for the scripted backend.
    assert.deepEqual(session.gaps.map((g) => g.concept_name), ["Base case"]);
    assert.ok(checked.nextQuestion?.question.includes(`line ${bugLine}`));
    const diagnostics = vscode.languages.getDiagnostics(uri);
    const gapDiagnostic = diagnostics.find((d) => d.code === "concept-gap");
    const noteDiagnostic = diagnostics.find((d) => d.code === "quality-note");
    assert.ok(gapDiagnostic && gapDiagnostic.range.start.line === bugLine - 1, "gap highlighted on the bug line");
    assert.equal(gapDiagnostic.severity, vscode.DiagnosticSeverity.Warning);
    assert.equal(noteDiagnostic?.severity, vscode.DiagnosticSeverity.Hint);
  } else {
    assert.ok(session.gaps.length > 0, "real model found at least one gap in the seeded bug");
  }

  const question = checked.nextQuestion;
  if (!question) {
    log("no question to answer (no gaps)");
    return;
  }
  await api.answer(question.gap_index, "It returns 1 for an empty directory because count starts at 1, and that's correct.");
  await waitFor("the answer to be judged", () => !api.state().answering, REAL_LLM ? 300 : 60);
  const answered = api.state();
  assert.equal(answered.status, "ready", `answer failed: ${answered.message}`);
  const gap = answered.session!.gaps.find((g) => g.index === question.gap_index)!;
  const materials = answered.materials[question.gap_index] ?? [];
  log(`verdict: ${gap.status}; mastery: ${JSON.stringify(answered.lastChange)}`);
  log(`materials: ${JSON.stringify(materials.map((m) => [m.kind, m.note, Boolean(m.thumbnailDataUri)]))}`);

  if (gap.status === "confirmed") {
    assert.deepEqual(materials.map((m) => m.kind).sort(), ["lecture", "slide"]);
    assert.ok(materials.find((m) => m.kind === "lecture")?.url?.includes("#t="));
  }
  if (!REAL_LLM) {
    assert.equal(gap.status, "confirmed");
    assert.deepEqual(answered.lastChange, { concept_id: "base_case", old_state: "unknown", new_state: "emerging" });
    assert.ok(answered.session!.complete && !answered.nextQuestion);
  }
  log("end-to-end flow passed");
}
