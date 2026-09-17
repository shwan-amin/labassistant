// Render the side panel as HTML. Pure (state in, string out) so it can be unit tested.
// Security: all text is escaped, and a strict Content Security Policy allows only
// our nonce-tagged style and script plus data: images.

import { renderConceptMapSvg, STATE_COLOURS } from "./conceptMap";
import { escapeHtml, formatTime } from "./html";
import { ConceptMap, GapStatus, MasteryChange, Material, Question, StudentSession } from "./types";

export interface MaterialWithImage extends Material {
  thumbnailDataUri?: string | null;
}

export interface PanelState {
  status: "idle" | "loading" | "ready" | "error";
  message?: string; // loading text or error text
  session?: StudentSession;
  nextQuestion?: Question | null;
  materials: Record<number, MaterialWithImage[]>;
  lastChange?: MasteryChange | null;
  answering: boolean;
  conceptMap?: ConceptMap;
}

export const initialPanelState = (): PanelState => ({ status: "idle", materials: {}, answering: false });

const STATUS_LABELS: Record<GapStatus, string> = {
  suspected: "Waiting for your answer",
  confirmed: "Worth revisiting",
  cleared: "You showed understanding",
  shown: "Worth revisiting",
};

export function renderPanel(state: PanelState, nonce: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lab Assistant</title>
<style nonce="${nonce}">${STYLES}</style>
</head>
<body>
${body(state)}
<script nonce="${nonce}">${SCRIPT}</script>
</body>
</html>`;
}

function body(state: PanelState): string {
  switch (state.status) {
    case "idle":
      return `<p class="muted">Highlight some code, right-click and choose <b>Check my understanding</b>.</p>`;
    case "loading":
      return `<div class="loading" role="status"><span class="spinner"></span>${escapeHtml(state.message ?? "Working...")}</div>`;
    case "error":
      return `<div class="card error" role="alert"><b>Something went wrong</b><p>${escapeHtml(state.message ?? "")}</p></div>`;
    default:
      return readyBody(state);
  }
}

function readyBody(state: PanelState): string {
  const session = state.session!;
  const parts: string[] = [
    `<p class="muted">Checked <code>${escapeHtml(session.selected_path)}</code> lines ${session.selection.start}-${session.selection.end}</p>`,
  ];

  if (state.lastChange) {
    const c = state.lastChange;
    parts.push(`<div class="card info">Your ${escapeHtml(conceptName(session, c.concept_id))} level: <b>${c.old_state}</b> → <b>${c.new_state}</b></div>`);
  }

  if (state.nextQuestion) {
    const q = state.nextQuestion;
    parts.push(`<section class="card question">
<h2>${escapeHtml(q.concept_name)}</h2>
<p>${escapeHtml(q.question)}</p>
<form id="answer-form" data-gap="${q.gap_index}">
<textarea id="answer" rows="4" maxlength="2000" placeholder="Explain in your own words..." ${state.answering ? "disabled" : ""}></textarea>
<button type="submit" ${state.answering ? "disabled" : ""}>${state.answering ? "Checking your answer..." : "Submit answer"}</button>
</form>
</section>`);
  } else if (session.gaps.length === 0) {
    parts.push(`<div class="card success">No concept gaps found in this selection. Nice work.</div>`);
  } else if (session.complete) {
    parts.push(`<div class="card success">All questions answered.</div>`);
  }

  for (const gap of session.gaps) {
    const lines = gap.evidence.map((e) => `${escapeHtml(e.path)}:${e.start_line}${e.end_line !== e.start_line ? `-${e.end_line}` : ""}`).join(", ");
    parts.push(`<section class="card gap ${gap.status}">
<h3>${escapeHtml(gap.concept_name)} <span class="badge">${STATUS_LABELS[gap.status]}</span></h3>
<p class="muted">Look at ${lines}</p>
${(state.materials[gap.index] ?? []).map(materialCard).join("")}
</section>`);
  }

  if (session.quality_notes.length > 0) {
    parts.push(`<section><h2>Code quality notes</h2>${session.quality_notes
      .map((n) => `<div class="card note"><b>${escapeHtml(n.category.replace(/_/g, " "))}</b> <span class="muted">${escapeHtml(n.path)}:${n.start_line}</span><p>${escapeHtml(n.explanation)}</p></div>`)
      .join("")}</section>`);
  }

  if (state.conceptMap) {
    const legend = (Object.keys(STATE_COLOURS) as (keyof typeof STATE_COLOURS)[])
      .map((s) => `<span class="legend-item"><span class="swatch" data-state="${s}"></span>${s}</span>`)
      .join("");
    parts.push(`<section><h2>Your concept map</h2><div class="legend">${legend}</div><div class="map">${renderConceptMapSvg(state.conceptMap)}</div></section>`);
  }
  return parts.join("\n");
}

function materialCard(material: MaterialWithImage): string {
  const link = material.url
    ? `<a href="#" data-url="${escapeHtml(material.url)}">${material.kind === "lecture" && material.start_seconds !== null ? `Watch from ${formatTime(material.start_seconds)}` : "Open slides"}</a>`
    : "";
  const image = material.thumbnailDataUri
    ? `<img src="${escapeHtml(material.thumbnailDataUri)}" alt="Slide ${material.slide_number ?? ""}">`
    : "";
  return `<div class="material ${material.kind}">${image}<p>${escapeHtml(material.note)}</p>${link}<p class="attribution">${escapeHtml(material.attribution)}</p></div>`;
}

function conceptName(session: StudentSession, conceptId: string): string {
  return session.gaps.find((g) => g.concept_id === conceptId)?.concept_name ?? conceptId;
}

const STYLES = `
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 0 12px 24px; }
h2 { font-size: 1.1em; margin: 0.4em 0; } h3 { font-size: 1em; margin: 0 0 0.3em; }
.muted { color: var(--vscode-descriptionForeground); }
.card { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 10px; margin: 10px 0; }
.card.error { border-color: var(--vscode-errorForeground); }
.card.success, .gap.cleared { border-color: #2e9e4f; }
.gap.confirmed, .gap.shown { border-color: #d9a000; }
.badge { font-size: 0.8em; font-weight: normal; padding: 1px 6px; border-radius: 8px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
textarea { width: 100%; box-sizing: border-box; font-family: inherit; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); }
button { margin-top: 6px; padding: 4px 12px; color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: none; border-radius: 3px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: default; }
a { color: var(--vscode-textLink-foreground); } a:hover { color: var(--vscode-textLink-activeForeground); }
.material { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--vscode-panel-border); }
.material img { max-width: 100%; border-radius: 4px; }
.attribution { font-size: 0.75em; color: var(--vscode-descriptionForeground); }
.loading { display: flex; gap: 8px; align-items: center; margin-top: 16px; }
.spinner { width: 14px; height: 14px; border: 2px solid var(--vscode-descriptionForeground); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.map svg { width: 100%; height: auto; } .map text { font-size: 12px; fill: #fff; } .map .edge { stroke: var(--vscode-descriptionForeground); stroke-width: 1.5; }
.legend { display: flex; gap: 12px; font-size: 0.85em; } .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; }
.swatch[data-state="unknown"] { background: ${STATE_COLOURS.unknown}; } .swatch[data-state="emerging"] { background: ${STATE_COLOURS.emerging}; } .swatch[data-state="secure"] { background: ${STATE_COLOURS.secure}; }
`;

const SCRIPT = `
const vscode = acquireVsCodeApi();
const form = document.getElementById("answer-form");
if (form) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const answer = document.getElementById("answer").value.trim();
    if (answer) {
      vscode.postMessage({ type: "answer", gapIndex: Number(form.dataset.gap), answer });
    }
  });
}
document.querySelectorAll("a[data-url]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    vscode.postMessage({ type: "openUrl", url: link.dataset.url });
  });
});
`;
