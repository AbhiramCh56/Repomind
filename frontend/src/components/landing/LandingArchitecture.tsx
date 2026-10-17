import { useState, type CSSProperties, type ReactNode } from "react"
import {
  BoxesIcon,
  BoxIcon,
  DatabaseIcon,
  FileCode2Icon,
  LockIcon,
  MonitorIcon,
  ZapIcon,
} from "lucide-react"

/**
 * The hero illustration on the public landing page.
 *
 * This is a fixed, hand-laid-out showcase of the product's output — the same
 * visual language (icon cards, accent borders, curved arrowed connectors) that
 * the real, data-driven `ArchitectureGraph` uses inside the app. It is drawn as
 * plain SVG rather than through the d3 renderer because the landing page is
 * pre-login and has no repository to lay out.
 *
 * Interactivity is deliberately light: hovering a card lifts it and lights up
 * the connectors attached to it.
 */

type NodeDef = {
  id: string
  x: number
  y: number
  title: string
  subtitle: string
  accent: string
  icon: ReactNode
}

const W = 190
const H = 72

const NODES: NodeDef[] = [
  {
    id: "frontend",
    x: 20,
    y: 184,
    title: "Frontend",
    subtitle: "React",
    accent: "#60a5fa",
    icon: <MonitorIcon width={20} height={20} />,
  },
  {
    id: "api",
    x: 290,
    y: 184,
    title: "API Layer",
    subtitle: "FastAPI",
    accent: "#a78bfa",
    icon: <ZapIcon width={20} height={20} />,
  },
  {
    id: "auth",
    x: 610,
    y: 60,
    title: "Auth Service",
    subtitle: "Authentication",
    accent: "#c084fc",
    icon: <LockIcon width={20} height={20} />,
  },
  {
    id: "core",
    x: 610,
    y: 184,
    title: "Core Service",
    subtitle: "Business logic",
    accent: "#a855f7",
    icon: <BoxIcon width={20} height={20} />,
  },
  {
    id: "rag",
    x: 610,
    y: 308,
    title: "RAG Service",
    subtitle: "Code understanding",
    accent: "#a78bfa",
    icon: <FileCode2Icon width={20} height={20} />,
  },
  {
    id: "postgres",
    x: 930,
    y: 88,
    title: "PostgreSQL",
    subtitle: "Database",
    accent: "#4ade80",
    icon: <DatabaseIcon width={20} height={20} />,
  },
  {
    id: "vector",
    x: 930,
    y: 252,
    title: "Vector DB",
    subtitle: "Embeddings",
    accent: "#60a5fa",
    icon: <BoxesIcon width={20} height={20} />,
  },
]

type EdgeDef = { id: string; d: string; from: string; to: string }

const EDGES: EdgeDef[] = [
  { id: "e1", d: "M 212 220 L 282 220", from: "frontend", to: "api" },
  { id: "e2", d: "M 480 220 C 546 220 546 96 602 96", from: "api", to: "auth" },
  { id: "e3", d: "M 480 220 L 602 220", from: "api", to: "core" },
  { id: "e4", d: "M 480 220 C 546 220 546 344 602 344", from: "api", to: "rag" },
  { id: "e5", d: "M 800 96 C 866 96 866 124 922 124", from: "auth", to: "postgres" },
  { id: "e6", d: "M 800 220 C 862 220 862 124 922 124", from: "core", to: "postgres" },
  { id: "e7", d: "M 800 220 C 862 220 862 288 922 288", from: "core", to: "vector" },
  { id: "e8", d: "M 800 344 C 866 344 866 288 922 288", from: "rag", to: "vector" },
]

export default function LandingArchitecture() {
  const [hover, setHover] = useState<string | null>(null)

  return (
    <svg
      viewBox="0 0 1140 400"
      className="w-full max-w-5xl"
      role="img"
      aria-label="Example repository architecture: a React frontend calls a FastAPI layer, which fans out to auth, core and RAG services backed by PostgreSQL and a vector database."
    >
      <defs>
        <marker
          id="la-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
        </marker>
      </defs>

      {EDGES.map((edge) => {
        const active = !hover || edge.from === hover || edge.to === hover
        return (
          <path
            key={edge.id}
            d={edge.d}
            className="la-edge"
            markerEnd="url(#la-arrow)"
            style={{
              opacity: active ? 1 : 0.12,
            }}
          />
        )
      })}

      {NODES.map((node, i) => (
        <g
          key={node.id}
          className="la-card"
          style={
            {
              "--accent": node.accent,
              animationDelay: `${i * 80}ms`,
            } as CSSProperties
          }
          onMouseEnter={() => setHover(node.id)}
          onMouseLeave={() => setHover(null)}
        >
          <rect
            className="la-card-bg"
            x={node.x}
            y={node.y}
            width={W}
            height={H}
            rx={14}
          />
          <rect
            className="la-chip"
            x={node.x + 14}
            y={node.y + 16}
            width={40}
            height={40}
            rx={10}
          />
          <g
            className="la-icon"
            transform={`translate(${node.x + 24}, ${node.y + 26})`}
          >
            {node.icon}
          </g>
          <text className="la-title" x={node.x + 66} y={node.y + 32}>
            {node.title}
          </text>
          <text className="la-sub" x={node.x + 66} y={node.y + 52}>
            {node.subtitle}
          </text>
        </g>
      ))}
    </svg>
  )
}
