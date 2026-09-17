// Turn a session into editor diagnostics. Pure, so it can be tested without VS Code.

import { StudentSession } from "./types";

export type DiagnosticKind = "concept-gap" | "quality-note";

export interface DiagnosticSpec {
  path: string;
  startLine: number; // 1-based, inclusive
  endLine: number;
  message: string;
  kind: DiagnosticKind;
}

const STATUS_TEXT: Record<string, string> = {
  suspected: "answer the question in the Lab Assistant panel",
  confirmed: "confirmed; see the teaching material in the panel",
  cleared: "cleared, nice work",
  shown: "see the Lab Assistant panel",
};

export function diagnosticsFor(session: StudentSession): DiagnosticSpec[] {
  const specs: DiagnosticSpec[] = [];
  for (const gap of session.gaps) {
    if (gap.status === "cleared") {
      continue; // understanding shown: no need to keep highlighting
    }
    for (const evidence of gap.evidence) {
      specs.push({
        path: evidence.path,
        startLine: evidence.start_line,
        endLine: evidence.end_line,
        message: `Possible gap in ${gap.concept_name}: ${STATUS_TEXT[gap.status]}.`,
        kind: "concept-gap",
      });
    }
  }
  for (const note of session.quality_notes) {
    specs.push({
      path: note.path,
      startLine: note.start_line,
      endLine: note.end_line,
      message: note.category === "other" ? note.explanation : `${capitalise(note.category.replace(/_/g, " "))}: ${note.explanation}`,
      kind: "quality-note",
    });
  }
  return specs;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
