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

const NODE_WIDTH = 150;
const NODE_HEIGHT = 34;
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
  for (const [level, ids] of [...rows.entries()].sort((a, b) => a[0] - b[0])) {
    const rowWidth = ids.length * (NODE_WIDTH + H_GAP) - H_GAP;
    const startX = (width - rowWidth) / 2;
    ids.forEach((id, i) => {
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
      `<text x="${n.x + NODE_WIDTH / 2}" y="${n.y + NODE_HEIGHT / 2 + 4}" text-anchor="middle">${escapeHtml(n.name)}</text></g>`,
  );
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Concept map">` +
    edges.join("") +
    boxes.join("") +
    `</svg>`
  );
}
