/**
 * Persistent SVG renderer for a directory/entrypoint tree.
 *
 * A single `<svg>` is created once and then *diffed* against each new graph, so
 * nodes keep their identity across polls and can glide to their new position
 * instead of being torn down and rebuilt. Layout comes from dagre; the motion is
 * driven by one d3 timer per render.
 *
 * Node ids from the backend are path based and stable, which is what makes the
 * diff possible: a node that is present in the new graph but not the previous
 * one is an *arrival*, and it grows out of its parent with its edge drawn in.
 */
import { useEffect, useId, useRef } from "react";
import { easeCubicInOut, select, timer, type Selection, type Timer } from "d3";
import {
  edgePath,
  fitText,
  hasSubline,
  layoutTree,
  prefersReducedMotion,
  subline,
} from "../lib/architecture";
import type { ArchEdge, ArchNode, Box, TreeGraph } from "../lib/architecture";

const ENTER_MS = 680;

const NODE_STYLES: Record<string, { fill: string; stroke: string }> = {
  root: { fill: "#eff6ff", stroke: "#3b82f6" },
  hub: { fill: "#eff6ff", stroke: "#3b82f6" },
  dir: { fill: "#f9fafb", stroke: "#d1d5db" },
  entrypoint: { fill: "#f0fdf4", stroke: "#86efac" },
  more: { fill: "#fffbeb", stroke: "#fcd34d" },
  none: { fill: "#fef2f2", stroke: "#fecaca" },
};

const EDGE_SOLID = "#94a3b8";
const EDGE_DASHED = "#cbd5e1";

type Seen = {
  /** Where each on-screen node currently is, updated every animation frame. */
  boxes: Map<string, Box>;
  timer: Timer | null;
};

type Root = Selection<SVGSVGElement, unknown, null, undefined>;

function ensureMarker(root: Root, markerId: string): void {
  let defs = root.select<SVGDefsElement>("defs.arch-defs");
  if (defs.empty()) defs = root.append("defs").attr("class", "arch-defs");

  defs.select(`marker#${markerId}`).remove();
  defs
    .append("marker")
    .attr("id", markerId)
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 8)
    .attr("refY", 0)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M 0 -3.5 L 8 0 L 0 3.5 z")
    .attr("fill", EDGE_SOLID);
}

function ensureLayers(root: Root): void {
  if (!root.select("g.arch-edges").empty()) return;
  // Edges first so the nodes paint on top of them.
  root.append("g").attr("class", "arch-edges");
  root.append("g").attr("class", "arch-nodes");
}

function renderTree(
  svg: SVGSVGElement,
  graph: TreeGraph,
  seen: Seen,
  markerId: string,
): () => void {
  const root = select(svg);
  ensureMarker(root, markerId);
  ensureLayers(root);

  seen.timer?.stop();

  const target = layoutTree(graph);
  // Every node in `graph.nodes` has a box: an edge is only added to the layout
  // engine when both endpoints exist, so dagre never drops a node.
  const boxOf = (id: string): Box => target.get(id)!;
  // A snapshot, not the live map: `seen.boxes` is replaced every frame below.
  const previous = seen.boxes;
  const firstRender = previous.size === 0;

  // Where each node starts. On the very first render nothing moves — the tree
  // just pops in. Afterwards an arrival grows out of its parent's current spot,
  // so a batch of new folders reads as the tree branching outwards.
  const starts = new Map<string, Box>();
  for (const node of graph.nodes) {
    const landed = target.get(node.id);
    if (!landed) continue;
    if (firstRender) {
      starts.set(node.id, landed);
      continue;
    }
    const known = previous.get(node.id);
    if (known) {
      starts.set(node.id, known);
      continue;
    }
    const parent = node.parent ? starts.get(node.parent) : undefined;
    starts.set(node.id, parent ?? landed);
  }

  const arriving = new Set(
    graph.nodes.filter((node) => !previous.has(node.id)).map((node) => node.id),
  );
  // An edge is drawn in unless both of its ends were already on screen.
  const drawingIn = new Set(
    graph.edges
      .filter((edge) => !previous.has(edge.source) || !previous.has(edge.target))
      .map((edge) => edge.id),
  );

  const edgeLayer = root.select<SVGGElement>("g.arch-edges");
  const edgeJoin = edgeLayer
    .selectAll<SVGPathElement, ArchEdge>("path.arch-edge")
    .data(graph.edges, (d) => d.id);
  const edges = edgeJoin
    .enter()
    .append("path")
    .attr("class", "arch-edge")
    .attr("fill", "none")
    .attr("stroke-width", 1.6)
    .attr("stroke-linecap", "round")
    .merge(edgeJoin);
  const edgesLeaving = edgeJoin.exit<ArchEdge>();
  edges.attr("stroke", (d) => (d.style === "dashed" ? EDGE_DASHED : EDGE_SOLID));

  const nodeLayer = root.select<SVGGElement>("g.arch-nodes");
  const nodeJoin = nodeLayer
    .selectAll<SVGGElement, ArchNode>("g.arch-node")
    .data(graph.nodes, (d) => d.id);

  const nodeEnter = nodeJoin.enter().append("g").attr("class", "arch-node");
  nodeEnter.append("rect").attr("rx", 9).attr("ry", 9);
  nodeEnter.append("title");
  nodeEnter.append("text").attr("class", "arch-node-label");
  nodeEnter.append("text").attr("class", "arch-node-sub");

  const nodes = nodeEnter.merge(nodeJoin);
  const nodesLeaving = nodeJoin.exit<ArchNode>();

  nodes
    .select<SVGRectElement>("rect")
    .attr("width", (d) => boxOf(d.id).width)
    .attr("height", (d) => boxOf(d.id).height)
    .attr("fill", (d) => NODE_STYLES[d.kind]?.fill ?? "#f9fafb")
    .attr("stroke", (d) => NODE_STYLES[d.kind]?.stroke ?? "#d1d5db")
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", (d) => (d.kind === "more" ? "5 4" : null));

  nodes
    .select<SVGTitleElement>("title")
    .text((d) => (hasSubline(d) ? `${d.label} \u2014 ${subline(d)}` : d.label));

  nodes
    .select<SVGTextElement>("text.arch-node-label")
    .attr("text-anchor", "middle")
    .attr("font-size", 12)
    .attr("font-weight", (d) => (d.kind === "root" || d.kind === "hub" ? 600 : 500))
    .attr("fill", "#111827")
    .attr("x", (d) => boxOf(d.id).width / 2)
    .attr("y", (d) => {
      const box = boxOf(d.id);
      return hasSubline(d) ? box.height / 2 - 2 : box.height / 2 + 4;
    })
    .text((d) => fitText(d.label, boxOf(d.id).width - 20));

  nodes
    .select<SVGTextElement>("text.arch-node-sub")
    .attr("text-anchor", "middle")
    .attr("font-size", 10)
    .attr("fill", "#6b7280")
    .attr("x", (d) => boxOf(d.id).width / 2)
    .attr("y", (d) => boxOf(d.id).height / 2 + 13)
    .text((d) => fitText(subline(d), boxOf(d.id).width - 20));

  let width = 0;
  let height = 0;
  target.forEach((box) => {
    width = Math.max(width, box.x + box.width);
    height = Math.max(height, box.y + box.height);
  });
  const viewWidth = Math.ceil(width + 12);
  const viewHeight = Math.ceil(height + 12);
  root
    .attr("width", viewWidth)
    .attr("height", viewHeight)
    .attr("viewBox", `0 0 ${viewWidth} ${viewHeight}`);

  const duration = prefersReducedMotion() ? 0 : ENTER_MS;

  seen.timer = timer((elapsed) => {
    const t = duration === 0 ? 1 : Math.min(1, elapsed / duration);
    const eased = easeCubicInOut(t);
    // Edges start drawing shortly after the nodes start moving, so the
    // arrowhead lands exactly as the node settles.
    const drawn = Math.min(1, Math.max(0, (t - 0.3) / 0.7));

    const live = new Map<string, Box>();
    nodes.each(function (d) {
      const to = boxOf(d.id);
      const from = starts.get(d.id) ?? to;
      const x = from.x + (to.x - from.x) * eased;
      const y = from.y + (to.y - from.y) * eased;
      const isArrival = arriving.has(d.id);
      const scale = isArrival ? 0.55 + 0.45 * eased : 1;
      const cx = to.width / 2;
      const cy = to.height / 2;
      // Scale about the node's own centre, otherwise it would shrink toward
      // its top-left corner and appear to detach from its edge.
      select(this)
        .attr(
          "transform",
          `translate(${x + cx} ${y + cy}) scale(${scale}) translate(${-cx} ${-cy})`,
        )
        .attr("opacity", isArrival ? eased : 1);
      live.set(d.id, { x, y, width: to.width, height: to.height });
    });

    nodesLeaving.each(function () {
      select(this).attr("opacity", 1 - eased);
    });

    edges.each(function (d) {
      const from = live.get(d.source);
      const to = live.get(d.target);
      if (!from || !to) {
        select(this).attr("opacity", 0);
        return;
      }
      const selection = select(this)
        .attr("d", edgePath(graph.direction, from, to))
        .attr("opacity", 1);

      if (drawingIn.has(d.id)) {
        // Hide the arrowhead and grow the line with a dash offset; the marker
        // is restored once the line reaches the target.
        const length = this.getTotalLength();
        selection
          .attr("marker-end", null)
          .attr("stroke-dasharray", `${length}`)
          .attr("stroke-dashoffset", `${length * (1 - drawn)}`);
      } else {
        selection
          .attr("stroke-dasharray", d.style === "dashed" ? "5 4" : null)
          .attr("stroke-dashoffset", null)
          .attr("marker-end", `url(#${markerId})`);
      }
    });

    edgesLeaving.attr("opacity", 1 - eased);
    // Keep the interrupted-animation case smooth: the next render starts from
    // wherever the nodes are *now*, not from where this one began.
    seen.boxes = live;

    if (t >= 1) {
      nodesLeaving.remove();
      edgesLeaving.remove();
      edges
        .attr("stroke-dasharray", (d) => (d.style === "dashed" ? "5 4" : null))
        .attr("stroke-dashoffset", null)
        .attr("marker-end", `url(#${markerId})`);
      return true;
    }
    return false;
  });

  return () => {
    seen.timer?.stop();
    seen.timer = null;
  };
}

export default function ArchitectureGraph({ graph }: { graph: TreeGraph }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const seenRef = useRef<Seen>({ boxes: new Map(), timer: null });
  const markerId = `arch-arrow-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    return renderTree(svg, graph, seenRef.current, markerId);
  }, [graph, markerId]);

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white p-4">
      <svg
        ref={svgRef}
        className="block"
        role="img"
        aria-label="Repository architecture diagram"
      />
    </div>
  );
}
