/**
 * Animated language-mix donut.
 *
 * Slice ids are language names, so a slice that was already on screen keeps its
 * colour and its arc is *tweened* to the new angle instead of being redrawn from
 * scratch. A language that appears for the first time grows out of its own
 * position as a zero-width wedge.
 */
import { useEffect, useMemo, useRef } from "react"
import {
  arc,
  easeCubicInOut,
  select,
  timer,
  type Selection,
  type Timer,
} from "d3"
import { prefersReducedMotion } from "../lib/architecture"
import type { ArchSlice, PieGraph } from "../lib/architecture"

const SIZE = 220
const RADIUS = SIZE / 2 - 6
const INNER = RADIUS * 0.55
const PIE_MS = 620

const PALETTE = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#6366f1",
  "#14b8a6",
  "#a855f7",
]

type Angle = { startAngle: number; endAngle: number }

type PieState = {
  angles: Map<string, Angle>
  timer: Timer | null
}

function hashId(id: string): number {
  let hash = 0
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  }
  return hash
}

/**
 * Assign palette colours purely from the slice ids. Starting at a hash of the
 * id keeps a language's colour stable as its count changes; linear probing stops
 * two slices in the same chart from sharing a colour.
 */
function assignColors(slices: ArchSlice[]): Map<string, string> {
  const colors = new Map<string, string>()
  const taken = new Set<number>()
  for (const slice of slices) {
    let index = hashId(slice.id) % PALETTE.length
    while (taken.has(index) && taken.size < PALETTE.length) {
      index = (index + 1) % PALETTE.length
    }
    taken.add(index)
    colors.set(slice.id, PALETTE[index])
  }
  return colors
}

function colorFor(id: string, colors: Map<string, string>): string {
  return colors.get(id) ?? PALETTE[hashId(id) % PALETTE.length]
}

function targetAngles(graph: PieGraph): Map<string, Angle> {
  const total =
    graph.slices.reduce((sum, slice) => sum + Math.max(0, slice.value), 0) || 1
  const angles = new Map<string, Angle>()
  let cursor = 0
  for (const slice of graph.slices) {
    const span = (Math.max(0, slice.value) / total) * Math.PI * 2
    angles.set(slice.id, { startAngle: cursor, endAngle: cursor + span })
    cursor += span
  }
  return angles
}

function renderPie(
  svg: SVGSVGElement,
  graph: PieGraph,
  colors: Map<string, string>,
  state: PieState,
): () => void {
  state.timer?.stop()

  const root: Selection<SVGSVGElement, unknown, null, undefined> = select(svg)
  let layer = root.select<SVGGElement>("g.pie")
  if (layer.empty()) {
    layer = root
      .append("g")
      .attr("class", "pie")
      .attr("transform", `translate(${SIZE / 2} ${SIZE / 2})`)
  }

  const target = targetAngles(graph)
  // Every slice in `graph.slices` has a target angle by construction.
  const angleOf = (id: string): Angle => target.get(id)!
  const previous = state.angles.size > 0 ? state.angles : null

  const starts = new Map<string, Angle>()
  for (const [id, to] of target) {
    const from = previous?.get(id)
    if (from) {
      starts.set(id, from)
    } else {
      const mid = (to.startAngle + to.endAngle) / 2
      starts.set(id, { startAngle: mid, endAngle: mid })
    }
  }

  // A slice that vanished collapses toward its own middle rather than blinking.
  const leaving = new Map<string, Angle>()
  if (previous) {
    for (const [id, from] of previous) {
      if (target.has(id)) continue
      const mid = (from.startAngle + from.endAngle) / 2
      leaving.set(id, { startAngle: mid, endAngle: mid })
    }
  }

  const arcFor = arc<Angle>().innerRadius(INNER).outerRadius(RADIUS).cornerRadius(2)

  const join = layer
    .selectAll<SVGPathElement, ArchSlice>("path.pie-slice")
    .data(graph.slices, (d) => d.id)
  const slices = join
    .enter()
    .append("path")
    .attr("class", "pie-slice")
    // The separator between wedges is the card surface behind the chart, so it
    // tracks the active theme automatically instead of being baked in white.
    .style("stroke", "var(--card)")
    .attr("stroke-width", 1)
    .merge(join)
  const slicesLeaving = join.exit<ArchSlice>()

  const fill = (slice: ArchSlice) => colorFor(slice.id, colors)
  slices.attr("fill", fill)
  slicesLeaving.attr("fill", fill)

  const duration = prefersReducedMotion() ? 0 : PIE_MS

  state.timer = timer((elapsed) => {
    const t = duration === 0 ? 1 : Math.min(1, elapsed / duration)
    const eased = easeCubicInOut(t)
    const now = new Map<string, Angle>()

    slices.each(function (d) {
      const to = angleOf(d.id)
      const from = starts.get(d.id) ?? to
      const angle: Angle = {
        startAngle: from.startAngle + (to.startAngle - from.startAngle) * eased,
        endAngle: from.endAngle + (to.endAngle - from.endAngle) * eased,
      }
      select(this).attr("d", arcFor(angle) ?? "")
      now.set(d.id, angle)
    })

    slicesLeaving.each(function (d) {
      const to = leaving.get(d.id)!
      const from = previous?.get(d.id) ?? to
      const angle: Angle = {
        startAngle: from.startAngle + (to.startAngle - from.startAngle) * eased,
        endAngle: from.endAngle + (to.endAngle - from.endAngle) * eased,
      }
      select(this)
        .attr("d", arcFor(angle) ?? "")
        .attr("opacity", 1 - eased)
      now.set(d.id, angle)
    })

    // Remember what is on screen now so an interrupted poll resumes smoothly.
    state.angles = now

    if (t >= 1) {
      slicesLeaving.remove()
      state.angles = new Map(target)
      return true
    }
    return false
  })

  return () => {
    state.timer?.stop()
    state.timer = null
  }
}

export default function LanguagePie({ graph }: { graph: PieGraph }) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const stateRef = useRef<PieState>({ angles: new Map(), timer: null })
  const colors = useMemo(() => assignColors(graph.slices), [graph])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    return renderPie(svg, graph, colors, stateRef.current)
  }, [graph, colors])

  const total = graph.slices.reduce((sum, slice) => sum + slice.value, 0)

  return (
    <div className="flex flex-wrap items-center gap-6 p-1">
      <svg
        ref={svgRef}
        width={SIZE}
        height={SIZE}
        className="shrink-0"
        role="img"
        aria-label={graph.title}
      />
      <ul className="space-y-1.5 text-sm">
        {graph.slices.map((slice) => {
          const percent = total > 0 ? Math.round((slice.value / total) * 100) : 0
          return (
            <li key={slice.id} className="flex items-center gap-2">
              <span
                className="inline-block size-3 shrink-0 rounded-sm"
                style={{ backgroundColor: colorFor(slice.id, colors) }}
              />
              <span className="font-medium text-foreground">{slice.label}</span>
              <span className="text-muted-foreground">
                {slice.value} files &middot; {percent}%
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
