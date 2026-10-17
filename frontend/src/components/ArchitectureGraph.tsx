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
 *
 * The diagram is also interactive. Pan/zoom is a single d3-zoom behaviour over a
 * `g.arch-viewport` wrapper, so the layout code never has to know about it.
 * Hovering a node lights up it and its neighbours; clicking one focuses its
 * subtree and dims everything else. Both are applied by toggling classes on the
 * live selections, so they never re-run the layout or the animation.
 */
import { useEffect, useId, useRef } from "react"
import { useTheme } from "next-themes"
import {
  easeCubicInOut,
  select,
  timer,
  zoom as d3Zoom,
  zoomIdentity,
  type Selection,
  type Timer,
  type ZoomBehavior,
} from "d3"
import { Maximize2Icon, MinusIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  edgePath,
  fitText,
  hasSubline,
  layoutTree,
  prefersReducedMotion,
  subline,
} from "../lib/architecture"
import type { ArchEdge, ArchNode, Box, TreeGraph } from "../lib/architecture"
import { ARCH_ICON_FALLBACK, ARCH_ICON_MARKUP } from "../lib/arch-icons"

const ENTER_MS = 680

/** Leading icon chip geometry, in the same units the node boxes use. */
const CHIP = 40
const CHIP_PAD = 14
const CHIP_GAP = 12
const ICON_SCALE = 20 / 24
const TEXT_X = CHIP_PAD + CHIP + CHIP_GAP

type NodeStyle = { fill: string; stroke: string }

type Palette = {
  node: Record<string, NodeStyle>
  edgeSolid: string
  edgeDashed: string
  label: string
  sub: string
}

// Diagrams are drawn with literal colours rather than theme tokens: the node
// fills need to be distinct per kind, and SVG fill/stroke attributes cannot
// resolve `var()` reliably. The two palettes below are the only place colours
// live; the renderer picks one from the active theme.
const LIGHT: Palette = {
  node: {
    root: { fill: "#eef2ff", stroke: "#6366f1" },
    hub: { fill: "#f5f3ff", stroke: "#8b5cf6" },
    dir: { fill: "#f8fafc", stroke: "#cbd5e1" },
    entrypoint: { fill: "#f0fdf4", stroke: "#86efac" },
    more: { fill: "#fffbeb", stroke: "#fcd34d" },
    none: { fill: "#fef2f2", stroke: "#fecaca" },
  },
  edgeSolid: "#94a3b8",
  edgeDashed: "#cbd5e1",
  label: "#0f172a",
  sub: "#64748b",
}

const DARK: Palette = {
  node: {
    root: { fill: "#312e81", stroke: "#818cf8" },
    hub: { fill: "#3b0764", stroke: "#a78bfa" },
    dir: { fill: "#334155", stroke: "#7c8aa5" },
    entrypoint: { fill: "#14532d", stroke: "#4ade80" },
    more: { fill: "#78350f", stroke: "#fbbf24" },
    none: { fill: "#7f1d1d", stroke: "#f87171" },
  },
  edgeSolid: "#64748b",
  edgeDashed: "#475569",
  label: "#f1f5f9",
  sub: "#cbd5e1",
}

type Seen = {
  /** Where each on-screen node currently is, updated every animation frame. */
  boxes: Map<string, Box>
  timer: Timer | null
}

/** Hover/selection live outside React so they never restart the animation. */
type Cursor = { current: string | null }

type Root = Selection<SVGSVGElement, unknown, null, undefined>
type Viewport = Selection<SVGGElement, unknown, null, undefined>

function style(node: ArchNode, palette: Palette): NodeStyle {
  return palette.node[node.kind] ?? palette.node.dir
}

function ensureMarker(root: Root, markerId: string, edgeSolid: string): void {
  let defs = root.select<SVGDefsElement>("defs.arch-defs")
  if (defs.empty()) defs = root.append("defs").attr("class", "arch-defs")

  defs.select(`marker#${markerId}`).remove()
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
    .attr("fill", edgeSolid)
}

/**
 * Everything is drawn inside a `g.arch-viewport` so the zoom behaviour only has
 * to move one element. Edges come before nodes so the cards paint on top.
 */
function ensureViewport(root: Root): Viewport {
  const existing = root.select<SVGGElement>("g.arch-viewport")
  if (!existing.empty()) return existing
  const viewport = root.append("g").attr("class", "arch-viewport")
  viewport.append("g").attr("class", "arch-edges")
  viewport.append("g").attr("class", "arch-nodes")
  return viewport
}

/** Direct children of each node, for walking a subtree on click. */
function childIndex(graph: TreeGraph): Map<string, string[]> {
  const children = new Map<string, string[]>()
  for (const node of graph.nodes) {
    if (!node.parent) continue
    const siblings = children.get(node.parent)
    if (siblings) siblings.push(node.id)
    else children.set(node.parent, [node.id])
  }
  return children
}

function renderTree(
  svg: SVGSVGElement,
  graph: TreeGraph,
  seen: Seen,
  hover: Cursor,
  selected: Cursor,
  markerId: string,
  palette: Palette,
): () => void {
  const root = select(svg)
  ensureMarker(root, markerId, palette.edgeSolid)
  const viewport = ensureViewport(root)

  seen.timer?.stop()

  const target = layoutTree(graph)
  // Every node in `graph.nodes` has a box: an edge is only added to the layout
  // engine when both endpoints exist, so dagre never drops a node.
  const boxOf = (id: string): Box => target.get(id)!
  // A snapshot, not the live map: `seen.boxes` is replaced every frame below.
  const previous = seen.boxes
  const firstRender = previous.size === 0

  // Where each node starts. On the very first render nothing moves — the tree
  // just pops in. Afterwards an arrival grows out of its parent's current spot,
  // so a batch of new folders reads as the tree branching outwards.
  const starts = new Map<string, Box>()
  for (const node of graph.nodes) {
    const landed = target.get(node.id)
    if (!landed) continue
    if (firstRender) {
      starts.set(node.id, landed)
      continue
    }
    const known = previous.get(node.id)
    if (known) {
      starts.set(node.id, known)
      continue
    }
    const parent = node.parent ? starts.get(node.parent) : undefined
    starts.set(node.id, parent ?? landed)
  }

  const arriving = new Set(
    graph.nodes.filter((node) => !previous.has(node.id)).map((node) => node.id),
  )
  // An edge is drawn in unless both of its ends were already on screen.
  const drawingIn = new Set(
    graph.edges
      .filter((edge) => !previous.has(edge.source) || !previous.has(edge.target))
      .map((edge) => edge.id),
  )

  const edgeLayer = viewport.select<SVGGElement>("g.arch-edges")
  const edgeJoin = edgeLayer
    .selectAll<SVGPathElement, ArchEdge>("path.arch-edge")
    .data(graph.edges, (d) => d.id)
  const edges = edgeJoin
    .enter()
    .append("path")
    .attr("class", "arch-edge")
    .attr("fill", "none")
    .attr("stroke-width", 1.6)
    .attr("stroke-linecap", "round")
    .merge(edgeJoin)
  const edgesLeaving = edgeJoin.exit<ArchEdge>()
  edges.attr("stroke", (d) =>
    d.style === "dashed" ? palette.edgeDashed : palette.edgeSolid,
  )

  const nodeLayer = viewport.select<SVGGElement>("g.arch-nodes")
  const nodeJoin = nodeLayer
    .selectAll<SVGGElement, ArchNode>("g.arch-node")
    .data(graph.nodes, (d) => d.id)

  const nodeEnter = nodeJoin.enter().append("g").attr("class", "arch-node")
  nodeEnter.append("rect").attr("class", "arch-node-box").attr("rx", 12).attr("ry", 12)
  nodeEnter.append("rect").attr("class", "arch-node-chip").attr("rx", 10)
  nodeEnter.append("g").attr("class", "arch-node-icon")
  nodeEnter.append("title")
  nodeEnter.append("text").attr("class", "arch-node-label")
  nodeEnter.append("text").attr("class", "arch-node-sub")

  const nodes = nodeEnter.merge(nodeJoin)
  const nodesLeaving = nodeJoin.exit<ArchNode>()

  nodes
    .select<SVGRectElement>("rect.arch-node-box")
    .attr("width", (d) => boxOf(d.id).width)
    .attr("height", (d) => boxOf(d.id).height)
    .attr("fill", (d) => style(d, palette).fill)
    .attr("fill-opacity", 0.55)
    .attr("stroke", (d) => style(d, palette).stroke)
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", (d) => (d.kind === "more" ? "5 4" : null))

  nodes
    .select<SVGRectElement>("rect.arch-node-chip")
    .attr("x", CHIP_PAD)
    .attr("y", (d) => (boxOf(d.id).height - CHIP) / 2)
    .attr("width", CHIP)
    .attr("height", CHIP)
    .attr("fill", (d) => style(d, palette).stroke)
    .attr("fill-opacity", 0.16)

  // The glyphs are inlined markup (see `lib/arch-icons.ts`); rebuild them only
  // when a node's kind changes, which for path-based ids is effectively never.
  nodes
    .select<SVGGElement>("g.arch-node-icon")
    .attr(
      "transform",
      (d) =>
        `translate(${CHIP_PAD + (CHIP - CHIP * ICON_SCALE) / 2}, ${
          (boxOf(d.id).height - CHIP * ICON_SCALE) / 2
        }) scale(${ICON_SCALE})`,
    )
    .attr("fill", "none")
    .attr("stroke-width", 2)
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .attr("stroke", (d) => style(d, palette).stroke)
    .each(function (d) {
      const host = select(this)
      if (host.attr("data-kind") === d.kind) return
      host.attr("data-kind", d.kind).html(ARCH_ICON_MARKUP[d.kind] ?? ARCH_ICON_FALLBACK)
    })

  nodes
    .select<SVGTitleElement>("title")
    .text((d) => (hasSubline(d) ? `${d.label} \u2014 ${subline(d)}` : d.label))

  nodes
    .select<SVGTextElement>("text.arch-node-label")
    .attr("text-anchor", "start")
    .attr("font-size", 12.5)
    .attr("font-weight", (d) => (d.kind === "root" || d.kind === "hub" ? 600 : 500))
    .attr("fill", palette.label)
    .attr("x", TEXT_X)
    .attr("y", (d) => {
      const box = boxOf(d.id)
      return hasSubline(d) ? box.height / 2 - 4 : box.height / 2 + 4
    })
    .text((d) => fitText(d.label, boxOf(d.id).width - TEXT_X - 12))

  nodes
    .select<SVGTextElement>("text.arch-node-sub")
    .attr("text-anchor", "start")
    .attr("font-size", 10.5)
    .attr("fill", palette.sub)
    .attr("x", TEXT_X)
    .attr("y", (d) => boxOf(d.id).height / 2 + 13)
    .text((d) => fitText(subline(d), boxOf(d.id).width - TEXT_X - 12))

  let width = 0
  let height = 0
  target.forEach((box) => {
    width = Math.max(width, box.x + box.width)
    height = Math.max(height, box.y + box.height)
  })
  const viewWidth = Math.ceil(width + 12)
  const viewHeight = Math.ceil(height + 12)
  // No width/height attributes: the element is sized by CSS to fill its card,
  // and the viewBox makes the whole tree fit until the reader zooms in.
  root.attr("viewBox", `0 0 ${viewWidth} ${viewHeight}`)

  // --- interaction: highlight the hovered neighbourhood / clicked subtree ---
  const children = childIndex(graph)
  const neighbours = new Map<string, Set<string>>()
  for (const node of graph.nodes) neighbours.set(node.id, new Set())
  for (const edge of graph.edges) {
    neighbours.get(edge.source)?.add(edge.target)
    neighbours.get(edge.target)?.add(edge.source)
  }

  const subtree = (id: string): Set<string> => {
    const out = new Set([id])
    const stack = [id]
    while (stack.length > 0) {
      const current = stack.pop()!
      for (const child of children.get(current) ?? []) {
        if (out.has(child)) continue
        out.add(child)
        stack.push(child)
      }
    }
    return out
  }

  const applyFocus = () => {
    const hovered = hover.current
    const chosen = selected.current
    const focus = hovered ?? chosen
    if (!focus) {
      nodes.classed("is-dim", false).classed("is-focus", false)
      edges.classed("is-dim", false)
      return
    }
    // Hovering looks one hop out; clicking keeps the whole subtree.
    const lit = hovered
      ? new Set([hovered, ...(neighbours.get(hovered) ?? [])])
      : subtree(chosen!)
    nodes
      .classed("is-dim", (d) => !lit.has(d.id))
      .classed("is-focus", (d) => d.id === focus)
    edges.classed("is-dim", (edge) =>
      hovered
        ? edge.source !== hovered && edge.target !== hovered
        : !(lit.has(edge.source) && lit.has(edge.target)),
    )
  }

  nodes
    .on("pointerenter", (_event: PointerEvent, d: ArchNode) => {
      hover.current = d.id
      applyFocus()
    })
    .on("pointerleave", () => {
      hover.current = null
      applyFocus()
    })
    .on("click", (event: MouseEvent, d: ArchNode) => {
      // Keep the click off the svg background handler below, which clears.
      event.stopPropagation()
      selected.current = selected.current === d.id ? null : d.id
      applyFocus()
    })

  root.on("click", () => {
    hover.current = null
    selected.current = null
    applyFocus()
  })

  applyFocus()

  const duration = prefersReducedMotion() ? 0 : ENTER_MS

  seen.timer = timer((elapsed) => {
    const t = duration === 0 ? 1 : Math.min(1, elapsed / duration)
    const eased = easeCubicInOut(t)
    // Edges start drawing shortly after the nodes start moving, so the
    // arrowhead lands exactly as the node settles.
    const drawn = Math.min(1, Math.max(0, (t - 0.3) / 0.7))

    const live = new Map<string, Box>()
    nodes.each(function (d) {
      const to = boxOf(d.id)
      const from = starts.get(d.id) ?? to
      const x = from.x + (to.x - from.x) * eased
      const y = from.y + (to.y - from.y) * eased
      const isArrival = arriving.has(d.id)
      const scale = isArrival ? 0.55 + 0.45 * eased : 1
      const cx = to.width / 2
      const cy = to.height / 2
      // Scale about the node's own centre, otherwise it would shrink toward
      // its top-left corner and appear to detach from its edge.
      select(this)
        .attr(
          "transform",
          `translate(${x + cx} ${y + cy}) scale(${scale}) translate(${-cx} ${-cy})`,
        )
        .attr("opacity", isArrival ? eased : 1)
      live.set(d.id, { x, y, width: to.width, height: to.height })
    })

    nodesLeaving.each(function () {
      select(this).attr("opacity", 1 - eased)
    })

    edges.each(function (d) {
      const from = live.get(d.source)
      const to = live.get(d.target)
      if (!from || !to) {
        select(this).attr("opacity", 0)
        return
      }
      const selection = select(this)
        .attr("d", edgePath(graph.direction, from, to))
        .attr("opacity", 1)

      if (drawingIn.has(d.id)) {
        // Hide the arrowhead and grow the line with a dash offset; the marker
        // is restored once the line reaches the target.
        const length = this.getTotalLength()
        selection
          .attr("marker-end", null)
          .attr("stroke-dasharray", `${length}`)
          .attr("stroke-dashoffset", `${length * (1 - drawn)}`)
      } else {
        selection
          .attr("stroke-dasharray", d.style === "dashed" ? "5 4" : null)
          .attr("stroke-dashoffset", null)
          .attr("marker-end", `url(#${markerId})`)
      }
    })

    edgesLeaving.attr("opacity", 1 - eased)
    // Keep the interrupted-animation case smooth: the next render starts from
    // wherever the nodes are *now*, not from where this one began.
    seen.boxes = live

    if (t >= 1) {
      nodesLeaving.remove()
      edgesLeaving.remove()
      edges
        .attr("stroke-dasharray", (d) => (d.style === "dashed" ? "5 4" : null))
        .attr("stroke-dashoffset", null)
        .attr("marker-end", `url(#${markerId})`)
      return true
    }
    return false
  })

  return () => {
    seen.timer?.stop()
    seen.timer = null
  }
}

export default function ArchitectureGraph({ graph }: { graph: TreeGraph }) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const seenRef = useRef<Seen>({ boxes: new Map(), timer: null })
  const hoverRef = useRef<string | null>(null)
  const selectedRef = useRef<string | null>(null)
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const markerId = `arch-arrow-${useId().replace(/[^a-zA-Z0-9]/g, "")}`
  const { resolvedTheme } = useTheme()
  const palette = resolvedTheme === "dark" ? DARK : LIGHT

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    return renderTree(
      svg,
      graph,
      seenRef.current,
      hoverRef,
      selectedRef,
      markerId,
      palette,
    )
  }, [graph, markerId, palette])

  // One zoom behaviour for the life of the component. It lives on the `<svg>`
  // itself, so the transform survives every re-render and poll.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const root = select(svg)
    const zoom = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on("zoom", (event) => {
        root
          .select("g.arch-viewport")
          .attr("transform", event.transform.toString())
      })
    root.call(zoom)
    zoomRef.current = zoom
    return () => {
      root.on(".zoom", null)
      zoomRef.current = null
    }
  }, [])

  const zoomBy = (factor: number) => {
    const svg = svgRef.current
    const zoom = zoomRef.current
    if (!svg || !zoom) return
    select(svg).call(zoom.scaleBy, factor)
  }

  const resetZoom = () => {
    const svg = svgRef.current
    const zoom = zoomRef.current
    if (!svg || !zoom) return
    select(svg).call(zoom.transform, zoomIdentity)
    selectedRef.current = null
  }

  return (
    <div className="relative h-[460px] overflow-hidden rounded-lg border bg-card/40">
      <svg
        ref={svgRef}
        className="size-full cursor-grab touch-none active:cursor-grabbing"
        role="img"
        aria-label="Repository architecture diagram. Scroll to zoom, drag to pan, and click a node to focus its subtree."
      />

      <div className="absolute right-2 top-2 flex flex-col gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="bg-card/80 backdrop-blur"
          onClick={() => zoomBy(1.3)}
          aria-label="Zoom in"
        >
          <PlusIcon className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="bg-card/80 backdrop-blur"
          onClick={() => zoomBy(1 / 1.3)}
          aria-label="Zoom out"
        >
          <MinusIcon className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="bg-card/80 backdrop-blur"
          onClick={resetZoom}
          aria-label="Reset view"
        >
          <Maximize2Icon className="size-3.5" />
        </Button>
      </div>

      <p className="pointer-events-none absolute bottom-2 left-3 text-xs text-muted-foreground">
        Scroll to zoom · drag to pan · click a node to focus
      </p>
    </div>
  )
}
