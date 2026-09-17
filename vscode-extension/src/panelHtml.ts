// Render the side panel as HTML. Pure (state in, string out) so it can be unit tested.
// Security: all text is escaped, and a strict Content Security Policy allows only
// our nonce-tagged style and script plus data: images.
//
// Layout, one card per concept gap:
//   concept + status  ->  evidence line chips  ->  question  ->  answer  ->  outcome  ->  learn more

import { escapeHtml, formatTime } from "./html";
import { GapStatus, MasteryChange, Material, Question, StudentGap, StudentSession } from "./types";

export interface MaterialWithImage extends Material {
  thumbnailDataUri?: string | null;
}

export interface PanelState {
  status: "idle" | "loading" | "ready" | "error";
  message?: string; // loading text or error text
  session?: StudentSession;
  nextQuestion?: Question | null;
  materials: Record<number, MaterialWithImage[]>;
  answers: Record<number, string>; // what the student wrote, shown back to them
  lastChange?: MasteryChange | null;
  answering: boolean;
}

export const initialPanelState = (): PanelState => ({ status: "idle", materials: {}, answers: {}, answering: false });

const STATUS: Record<GapStatus, { label: string; tone: string }> = {
  suspected: { label: "Question", tone: "neutral" },
  confirmed: { label: "Worth revisiting", tone: "warn" },
  shown: { label: "Worth revisiting", tone: "warn" },
  cleared: { label: "Understood", tone: "good" },
};

const ICONS = {
  file: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 1.5h5l3.5 3.5v9.5h-8.5z M9 1.5v3.5h3.5" /></svg>`,
  play: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.5v9l7.5-4.5z" /></svg>`,
  check: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7" /></svg>`,
  arrow: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5l4.5 4.5-4.5 4.5" /></svg>`,
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
<main>${body(state)}</main>
<script nonce="${nonce}">${SCRIPT}</script>
</body>
</html>`;
}

function body(state: PanelState): string {
  switch (state.status) {
    case "idle":
      return `<div class="empty"><p class="lead">Check your understanding</p><p class="muted">Highlight some code, right-click and choose <b>Lab Assistant: Check my understanding</b>.</p></div>`;
    case "loading":
      return `<div class="empty" role="status"><span class="spinner"></span><p class="muted">${escapeHtml(state.message ?? "Working...")}</p></div>`;
    case "error":
      return `<div class="card error" role="alert"><p class="lead">Something went wrong</p><p>${escapeHtml(state.message ?? "")}</p></div>`;
    default:
      return readyBody(state);
  }
}

function readyBody(state: PanelState): string {
  const session = state.session!;
  const parts = [
    `<header class="header"><span class="eyebrow">Lab Assistant</span>` +
      `<span class="target">${ICONS.file}${escapeHtml(session.selected_path)} · lines ${session.selection.start}–${session.selection.end}</span></header>`,
  ];

  if (session.gaps.length === 0) {
    parts.push(`<div class="card done"><span class="icon good">${ICONS.check}</span><div><p class="lead">No concept gaps found</p><p class="muted">Nothing in this selection suggests a misunderstanding. Nice work.</p></div></div>`);
  }
  for (const gap of session.gaps) {
    parts.push(gapCard(gap, state));
  }
  if (session.gaps.length > 0 && session.complete) {
    parts.push(`<p class="muted small center">All questions answered.</p>`);
  }
  if (session.quality_notes.length > 0) {
    parts.push(qualityNotes(session));
  }

  const attributions = [...new Set(Object.values(state.materials).flat().map((m) => m.attribution))];
  if (attributions.length > 0) {
    parts.push(`<footer class="footer">${attributions.map(escapeHtml).join("<br>")}</footer>`);
  }
  return parts.join("\n");
}

function gapCard(gap: StudentGap, state: PanelState): string {
  const status = STATUS[gap.status];
  const isCurrent = state.nextQuestion?.gap_index === gap.index;
  const question = isCurrent ? state.nextQuestion!.question : gap.question;
  const answer = state.answers[gap.index];
  const change = state.lastChange && state.lastChange.concept_id === gap.concept_id ? state.lastChange : null;
  const materials = state.materials[gap.index] ?? [];

  const chips = gap.evidence
    .map((e) => {
      const lines = e.start_line === e.end_line ? `line ${e.start_line}` : `lines ${e.start_line}–${e.end_line}`;
      return `<button class="chip" data-path="${escapeHtml(e.path)}" data-line="${e.start_line}" title="Go to code">${escapeHtml(e.path)} · ${lines}</button>`;
    })
    .join("");

  const sections = [
    `<div class="card-head"><h2>${escapeHtml(gap.concept_name)}</h2><span class="pill ${status.tone}">${status.label}</span></div>`,
    `<div class="chips">${chips}</div>`,
  ];

  if (question) {
    sections.push(`<blockquote class="question">${escapeHtml(question)}</blockquote>`);
  }
  if (answer) {
    sections.push(`<div class="answer"><span class="label">Your answer</span><p>${escapeHtml(answer)}</p></div>`);
  }
  if (gap.status === "suspected") {
    if (isCurrent && !(state.answering && answer)) {
      sections.push(`<form id="answer-form" data-gap="${gap.index}">
<textarea id="answer" rows="3" maxlength="2000" placeholder="Explain your thinking in your own words..." ${state.answering ? "disabled" : ""}></textarea>
<div class="actions"><button class="primary" type="submit" ${state.answering ? "disabled" : ""}>Submit answer</button></div>
</form>`);
    } else if (state.answering) {
      sections.push(`<div class="thinking"><span class="spinner small"></span><span class="muted">Checking your answer...</span></div>`);
    } else {
      sections.push(`<p class="muted small">Answer the question above first.</p>`);
    }
  } else {
    sections.push(outcome(gap.status, change, gap.concept_name));
  }

  if (materials.length > 0) {
    sections.push(`<div class="learn"><span class="label">Learn more</span>${materials.map(materialCard).join("")}</div>`);
  }
  return `<article class="card gap ${status.tone}">${sections.join("\n")}</article>`;
}

function outcome(status: GapStatus, change: MasteryChange | null, conceptName: string): string {
  const text =
    status === "cleared"
      ? "You explained this well."
      : "This is worth another look. The lecture moment and slide below explain it.";
  const level = change
    ? `<span class="level">${escapeHtml(conceptName)} level: ${escapeHtml(change.old_state)} ${ICONS.arrow} <b>${escapeHtml(change.new_state)}</b></span>`
    : "";
  return `<div class="outcome ${status === "cleared" ? "good" : "warn"}"><p>${text}</p>${level}</div>`;
}

function materialCard(material: MaterialWithImage): string {
  const url = material.url ? ` data-url="${escapeHtml(material.url)}"` : "";
  if (material.kind === "lecture") {
    const time =
      material.start_seconds !== null
        ? `${formatTime(material.start_seconds)}${material.end_seconds !== null ? `–${formatTime(material.end_seconds)}` : ""}`
        : "Lecture";
    return `<button class="resource lecture"${url}>
<span class="play">${ICONS.play}</span>
<span class="resource-text"><span class="resource-title">Watch ${time}</span><span class="resource-sub">${escapeHtml(material.source_title)}</span></span>
</button>`;
  }
  const image = material.thumbnailDataUri
    ? `<img src="${escapeHtml(material.thumbnailDataUri)}" alt="Slide ${material.slide_number ?? ""}">`
    : "";
  return `<button class="resource slide"${url}>
${image}
<span class="resource-text"><span class="resource-title">Slide ${material.slide_number ?? ""}</span><span class="resource-sub">${escapeHtml(material.source_title)}</span></span>
</button>`;
}

function qualityNotes(session: StudentSession): string {
  const notes = session.quality_notes
    .map((n) => {
      const category = n.category === "other" ? "Note" : capitalise(n.category.replace(/_/g, " "));
      return `<li><div class="note-head"><b>${escapeHtml(category)}</b><button class="chip small" data-path="${escapeHtml(n.path)}" data-line="${n.start_line}">${escapeHtml(n.path)} · line ${n.start_line}</button></div><p>${escapeHtml(n.explanation)}</p></li>`;
    })
    .join("");
  return `<details class="notes"><summary>Code quality notes (${session.quality_notes.length})</summary><ul>${notes}</ul></details>`;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const STYLES = `
:root {
  --radius: 10px;
  --border: var(--vscode-widget-border, rgba(128,128,128,0.25));
  --surface: color-mix(in srgb, var(--vscode-foreground) 4%, transparent);
  --muted: var(--vscode-descriptionForeground);
  --accent: var(--vscode-textLink-foreground);
  --warn: var(--vscode-editorWarning-foreground, #d9a000);
  --good: var(--vscode-testing-iconPassed, #3fb950);
}
* { box-sizing: border-box; }
body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size, 13px); color: var(--vscode-foreground); margin: 0; padding: 16px; line-height: 1.5; }
main { max-width: 640px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
p { margin: 0; }
svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
.muted { color: var(--muted); } .small { font-size: 0.9em; } .center { text-align: center; }
.lead { font-weight: 600; font-size: 1.05em; }
.label { display: block; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 6px; }

.header { display: flex; flex-direction: column; gap: 2px; }
.eyebrow { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
.target { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.card.gap.warn { border-left: 3px solid var(--warn); }
.card.gap.good { border-left: 3px solid var(--good); }
.card.error { border-left: 3px solid var(--vscode-errorForeground); }
.card.done { flex-direction: row; align-items: flex-start; gap: 12px; }
.icon.good { color: var(--good); } .icon svg { width: 20px; height: 20px; }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-head h2 { font-size: 1.15em; margin: 0; }
.pill { font-size: 0.75em; padding: 2px 10px; border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
.pill.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
.pill.good { color: var(--good); border-color: color-mix(in srgb, var(--good) 45%, transparent); }
.pill.neutral { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, transparent); }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
button { font: inherit; color: inherit; cursor: pointer; }
.chip { background: transparent; border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; font-family: var(--vscode-editor-font-family, monospace); font-size: 0.85em; color: var(--muted); }
.chip:hover { color: var(--accent); border-color: var(--accent); }
.chip.small { font-size: 0.8em; padding: 0 6px; }

.question { margin: 0; padding: 4px 0 4px 12px; border-left: 3px solid var(--accent); font-size: 1.05em; }
.answer p { color: var(--muted); font-style: italic; }

textarea { width: 100%; resize: vertical; font: inherit; padding: 10px; border-radius: 8px; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border, var(--border)); }
textarea:focus { outline: 1px solid var(--vscode-focusBorder); }
.actions { display: flex; justify-content: flex-end; margin-top: 8px; }
.primary { padding: 6px 16px; border-radius: 6px; border: none; color: var(--vscode-button-foreground); background: var(--vscode-button-background); }
.primary:hover { background: var(--vscode-button-hoverBackground); }
.primary:disabled { opacity: 0.5; cursor: default; }

.outcome { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.level { display: inline-flex; align-items: center; gap: 4px; font-size: 0.85em; color: var(--muted); }
.thinking { display: flex; align-items: center; gap: 8px; }

.learn { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--border); }
.resource { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left; padding: 10px; border-radius: 8px; border: 1px solid var(--border); background: transparent; }
.resource:hover { border-color: var(--accent); }
.resource-text { display: flex; flex-direction: column; min-width: 0; }
.resource-title { font-weight: 600; }
.resource-sub { font-size: 0.85em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.play { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: var(--accent); color: var(--vscode-editor-background, #000); flex-shrink: 0; }
.play svg { fill: currentColor; stroke: none; width: 14px; height: 14px; margin-left: 2px; }
.resource.slide { flex-direction: column; align-items: stretch; }
.resource.slide img { width: 100%; max-height: 220px; object-fit: contain; border-radius: 6px; background: #fff; }

.notes { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; }
.notes summary { cursor: pointer; color: var(--muted); }
.notes ul { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.note-head { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }

.footer { font-size: 0.75em; color: var(--muted); border-top: 1px solid var(--border); padding-top: 10px; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; padding: 40px 12px; }
.spinner { width: 20px; height: 20px; border: 2px solid var(--muted); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
.spinner.small { width: 12px; height: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
`;

const SCRIPT = `
const vscode = acquireVsCodeApi();
const form = document.getElementById("answer-form");
if (form) {
  const box = document.getElementById("answer");
  box.focus();
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const answer = box.value.trim();
    if (answer) {
      vscode.postMessage({ type: "answer", gapIndex: Number(form.dataset.gap), answer });
    }
  });
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      form.requestSubmit();
    }
  });
}
document.querySelectorAll("[data-url]").forEach((element) => {
  element.addEventListener("click", () => vscode.postMessage({ type: "openUrl", url: element.dataset.url }));
});
document.querySelectorAll("[data-path]").forEach((element) => {
  element.addEventListener("click", () => vscode.postMessage({ type: "reveal", path: element.dataset.path, line: Number(element.dataset.line) }));
});
`;
