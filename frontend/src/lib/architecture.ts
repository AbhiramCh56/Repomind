/**
 * Types and layout for the architecture diagrams.
 *
 * The backend sends each view twice: a Mermaid string (kept for exported
 * documents) and a structured graph. Only the structured graph is rendered here.
 * Its node ids are path based (`root`, `dir:app/services`, `ep:app/main.py`), so
 * they stay the same as an import progresses and the SVG renderer can tell an
 * *arrival* apart from a node that merely changed its file count.
 */
import * as graphlib from "dagre-d3-es/src/graphlib/index.js";
import { layout as dagreLayout } from "dagre-d3-es/src/dagre/index.js";

export type NodeKind = "root" | "dir" | "more" | "hub" | "entrypoint" | "none";

export interface ArchNode {
  id: string;
  label: string;
  kind: NodeKind;
  parent: string | null;
  files: number;
  sublabel: string;
}

export interface ArchEdge {
  id: string;
  source: string;
  target: string;
  style: "solid" | "dashed";
}

export interface TreeGraph {
  type: "tree";
  direction: "TD" | "LR";
  nodes: ArchNode[];
  edges: ArchEdge[];
}

export interface ArchSlice {
  id: string;
  label: string;
  value: number;
}

export interface PieGraph {
  type: "pie";
  title: string;
  slices: ArchSlice[];
}

/** A node's box in SVG coordinates (top-left origin, y grows downward). */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Rough advance width of the 12px UI font, used to size nodes to their text. */
const CHAR_WIDTH = 7;
const MIN_WIDTH = 104;
const MAX_WIDTH = 264;

export function hasSubline(node: ArchNode): boolean {
  return Boolean(node.sublabel) || node.files > 0;
}

export function subline(node: ArchNode): string {
  if (node.sublabel) return node.sublabel;
  return node.files > 0 ? `${node.files} files` : "";
}

/** Shrink a label to what fits inside `maxWidth`, keeping a `<title>` for the rest. */
export function fitText(text: string, maxWidth: number): string {
  const max = Math.max(3, Math.floor(maxWidth / CHAR_WIDTH));
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}\u2026`;
}

function nodeSize(node: ArchNode) {
  const lines = [node.label, hasSubline(node) ? subline(node) : ""];
  const longest = Math.max(...lines.map((line) => line.length), 6);
  const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, longest * CHAR_WIDTH + 28));
  return { width, height: hasSubline(node) ? 46 : 34 };
}

/**
 * Run the dagre ranking pass and return where every node should sit.
 *
 * Pure: no DOM access. The renderer diffs these boxes against the previous
 * frame's to decide what moves, what enters and what leaves.
 */
export function layoutTree(graph: TreeGraph): Map<string, Box> {
  const engine = new graphlib.Graph();
  engine.setGraph({
    rankdir: graph.direction,
    nodesep: 36,
    ranksep: 64,
    marginx: 12,
    marginy: 12,
  });
  engine.setDefaultEdgeLabel(() => ({}));

  const sizes = new Map<string, { width: number; height: number }>();
  for (const node of graph.nodes) {
    const size = nodeSize(node);
    sizes.set(node.id, size);
    engine.setNode(node.id, { width: size.width, height: size.height });
  }
  for (const edge of graph.edges) {
    if (sizes.has(edge.source) && sizes.has(edge.target)) {
      engine.setEdge(edge.source, edge.target);
    }
  }

  dagreLayout(engine, {});

  const boxes = new Map<string, Box>();
  for (const node of graph.nodes) {
    const placed = engine.node(node.id);
    const size = sizes.get(node.id);
    if (!placed || !size) continue;
    boxes.set(node.id, {
      x: placed.x - size.width / 2,
      y: placed.y - size.height / 2,
      width: size.width,
      height: size.height,
    });
  }
  return boxes;
}

/**
 * Cubic path from a node's edge to its parent's edge. Recomputed every frame so
 * an edge tracks the nodes it connects while they glide into place.
 */
export function edgePath(direction: TreeGraph["direction"], from: Box, to: Box): string {
  if (direction === "LR") {
    const sx = from.x + from.width;
    const sy = from.y + from.height / 2;
    const tx = to.x;
    const ty = to.y + to.height / 2;
    const mx = (sx + tx) / 2;
    return `M ${sx} ${sy} C ${mx} ${sy} ${mx} ${ty} ${tx} ${ty}`;
  }
  const sx = from.x + from.width / 2;
  const sy = from.y + from.height;
  const tx = to.x + to.width / 2;
  const ty = to.y;
  const my = (sy + ty) / 2;
  return `M ${sx} ${sy} C ${sx} ${my} ${tx} ${my} ${tx} ${ty}`;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
