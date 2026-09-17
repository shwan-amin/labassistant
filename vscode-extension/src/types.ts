// Mirrors src/labassistant/api/schemas.py. Keep the two in sync.

export type GapStatus = "suspected" | "confirmed" | "cleared" | "shown";
export type MasteryState = "unknown" | "emerging" | "secure";

export interface ProjectFile {
  path: string;
  content: string;
}

export interface LineRange {
  start: number; // 1-based, inclusive
  end: number;
}

export interface CheckRequest {
  files: ProjectFile[];
  selected_path: string;
  selection: LineRange;
  explanation?: string;
  student_id?: string;
  skip_questioning?: boolean;
}

export interface StudentEvidence {
  path: string;
  start_line: number;
  end_line: number;
  test_ids: string[];
}

export interface StudentGap {
  index: number;
  concept_id: string;
  concept_name: string;
  status: GapStatus;
  evidence: StudentEvidence[];
  question: string | null;
}

export interface StudentQualityNote {
  category: string;
  path: string;
  start_line: number;
  end_line: number;
  explanation: string;
}

export interface StudentSession {
  session_id: string;
  selected_path: string;
  selection: LineRange;
  complete: boolean;
  gaps: StudentGap[];
  quality_notes: StudentQualityNote[];
}

export interface Question {
  gap_index: number;
  concept_name: string;
  question: string;
}

export interface CheckResponse {
  session: StudentSession;
  next_question: Question | null;
}

export interface Material {
  kind: "lecture" | "slide";
  source_title: string;
  note: string;
  url: string | null;
  start_seconds: number | null;
  end_seconds: number | null;
  slide_number: number | null;
  thumbnail_url: string | null;
  attribution: string;
}

export interface MasteryChange {
  concept_id: string;
  old_state: MasteryState;
  new_state: MasteryState;
}

export interface AnswerResponse {
  gap_index: number;
  status: GapStatus;
  mastery_change: MasteryChange | null;
  materials: Material[];
  next_question: Question | null;
  complete: boolean;
}

export interface ConceptNode {
  id: string;
  name: string;
  description: string;
  state: MasteryState;
  prerequisites: string[];
}

export interface ConceptEdge {
  source: string;
  target: string;
}

export interface ConceptMap {
  student_id: string;
  topic: string;
  nodes: ConceptNode[];
  edges: ConceptEdge[];
}
