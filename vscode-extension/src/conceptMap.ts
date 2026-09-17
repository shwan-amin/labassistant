// Lay out the concept graph in levels (prerequisites above the concepts that need
// them) and render it as SVG coloured by mastery.

import { escapeHtml } from "./html";
import { ConceptMap, MasteryState } from "./types";

export interface PositionedNode {
  id: string;
  name: string;
  state: MasteryState;
  level: number;
  x: number;
  y: number;
}

const NODE_WIDTH = 160;
const NODE_HEIGHT = 40;
const MAX_LINE_CHARS = 20;
const H_GAP = 20;
const V_GAP = 36;

export const STATE_COLOURS: Record<MasteryState, string> = {
  unknown: "#8a8a8a",
  emerging: "#d9a000",
  secure: "#2e9e4f",
};

/** A node's level is the length of the longest prerequisite chain leading to it. */
export function levels(map: ConceptMap): Map<string, number> {
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  const memo = new Map<string, number>();
  const visit = (id: string, stack: Set<string>): number => {
    const cached = memo.get(id);
    if (cached !== undefined) {
      return cached;
    }
    if (stack.has(id)) {
      return 0; // the backend rejects cycles; this only guards against bad data
    }
    stack.add(id);
    const prereqs = byId.get(id)?.prerequisites.filter((p) => byId.has(p)) ?? [];
    const level = prereqs.length === 0 ? 0 : 1 + Math.max(...prereqs.map((p) => visit(p, stack)));
    stack.delete(id);
    memo.set(id, level);
    return level;
  };
  map.nodes.forEach((n) => visit(n.id, new Set()));
  return memo;
}

export function layout(map: ConceptMap): { nodes: PositionedNode[]; width: number; height: number } {
  const nodeLevels = levels(map);
  const rows = new Map<number, string[]>();
  for (const node of map.nodes) {
    const level = nodeLevels.get(node.id) ?? 0;
    rows.set(level, [...(rows.get(level) ?? []), node.id]);
  }
  const widest = Math.max(1, ...[...rows.values()].map((r) => r.length));
  const width = widest * (NODE_WIDTH + H_GAP) + H_GAP;
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  const nodes: PositionedNode[] = [];
  const xById = new Map<string, number>();
  for (const [level, unordered] of [...rows.entries()].sort((a, b) => a[0] - b[0])) {
    // Barycentre heuristic: place each concept under the average position of its
    // prerequisites, which keeps edges short and reduces crossings.
    const centre = (id: string): number => {
      const xs = (byId.get(id)?.prerequisites ?? []).map((p) => xById.get(p)).filter((x): x is number => x !== undefined);
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
    };
    const ids = level === 0 ? unordered : [...unordered].sort((a, b) => centre(a) - centre(b));
    const rowWidth = ids.length * (NODE_WIDTH + H_GAP) - H_GAP;
    const startX = (width - rowWidth) / 2;
    ids.forEach((id, i) => {
      xById.set(id, startX + i * (NODE_WIDTH + H_GAP));
      const node = byId.get(id)!;
      nodes.push({
        id,
        name: node.name,
        state: node.state,
        level,
        x: startX + i * (NODE_WIDTH + H_GAP),
        y: H_GAP + level * (NODE_HEIGHT + V_GAP),
      });
    });
  }
  const height = H_GAP * 2 + (Math.max(0, ...nodes.map((n) => n.level)) + 1) * (NODE_HEIGHT + V_GAP) - V_GAP;
  return { nodes, width, height };
}

export function renderConceptMapSvg(map: ConceptMap): string {
  const { nodes, width, height } = layout(map);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = map.edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => {
      const from = byId.get(e.source)!;
      const to = byId.get(e.target)!;
      return `<line x1="${from.x + NODE_WIDTH / 2}" y1="${from.y + NODE_HEIGHT}" x2="${to.x + NODE_WIDTH / 2}" y2="${to.y}" class="edge" />`;
    });
  const boxes = nodes.map(
    (n) =>
      `<g class="node ${n.state}"><title>${escapeHtml(n.name)}: ${n.state}</title>` +
      `<rect x="${n.x}" y="${n.y}" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="6" fill="${STATE_COLOURS[n.state]}" />` +
      textLines(n.name, n.x + NODE_WIDTH / 2, n.y + NODE_HEIGHT / 2) +
      `</g>`,
  );
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Concept map">` +
    edges.join("") +
    boxes.join("") +
    `</svg>`
  );
}

/** Split a name into at most two lines at a space, so long names fit their box. */
export function wrapName(name: string, maxChars = MAX_LINE_CHARS): string[] {
  if (name.length <= maxChars) {
    return [name];
  }
  const words = name.split(" ");
  let best = 1;
  for (let i = 1; i < words.length; i++) {
    const first = words.slice(0, i).join(" ").length;
    const second = words.slice(i).join(" ").length;
    const bestFirst = words.slice(0, best).join(" ").length;
    const bestSecond = words.slice(best).join(" ").length;
    if (Math.max(first, second) < Math.max(bestFirst, bestSecond)) {
      best = i;
    }
  }
  return words.length > 1 ? [words.slice(0, best).join(" "), words.slice(best).join(" ")] : [name];
}

function textLines(name: string, centreX: number, centreY: number): string {
  const lines = wrapName(name);
  const lineHeight = 14;
  const firstY = centreY + 4 - ((lines.length - 1) * lineHeight) / 2;
  const spans = lines
    .map((line, i) => `<tspan x="${centreX}" y="${firstY + i * lineHeight}">${escapeHtml(line)}</tspan>`)
    .join("");
  return `<text text-anchor="middle">${spans}</text>`;
}
