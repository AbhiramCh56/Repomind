import { useEffect, useState, type ReactNode } from "react"
import { CircleAlertIcon } from "lucide-react"

import api from "../api/axiosConfig"
import ArchitectureGraph from "./ArchitectureGraph"
import LanguagePie from "./LanguagePie"
import type { PieGraph, TreeGraph } from "../lib/architecture"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"

// The live preview polls while a repository is still indexing; the backend
// commits embedding progress per batch, so a coarse interval is plenty.
const POLL_INTERVAL_MS = 2000

type Diagrams = Record<string, TreeGraph | PieGraph>

type DiagramProgress = {
  embedded: number
  chunk_count: number
  live_files: number
  total_files: number
}

function progressText(status: string, progress: DiagramProgress | null): string {
  if (status === "cloning") return "Cloning the repository…"
  if (status === "processing") {
    const files = progress ? `${progress.live_files}/${progress.total_files}` : "0/0"
    return `Scanning files — ${files} files identified.`
  }
  if (status === "embedding" && progress) {
    return `${progress.embedded}/${progress.chunk_count} chunks embedded.`
  }
  if (progress) {
    return `${progress.embedded}/${progress.chunk_count} chunks embedded.`
  }
  return "Updating as indexing progresses."
}

/** A titled group in the side rail. */
function RailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  )
}

/**
 * The entrypoints as a plain list.
 *
 * The manifest models them as a flat tree fanning out of one hub, which is a
 * poor fit for a narrow rail: at rail width the tree would be a column of cards
 * with connector lines fighting the panel edges. The interesting part is the
 * list of paths and their language, so render exactly that.
 */
function EntrypointList({ graph }: { graph?: TreeGraph }) {
  const entrypoints = graph?.nodes.filter((node) => node.kind === "entrypoint") ?? []
  const more = graph?.nodes.find((node) => node.kind === "more")

  if (entrypoints.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No conventional entrypoints detected.
      </p>
    )
  }

  return (
    <ul className="space-y-0.5">
      {entrypoints.map((node) => (
        <li key={node.id} className="rounded-md px-2 py-1.5" title={node.label}>
          <div className="truncate font-mono text-xs text-foreground">
            {node.label}
          </div>
          {node.sublabel && (
            <div className="truncate text-xs text-muted-foreground">
              {node.sublabel}
            </div>
          )}
        </li>
      ))}
      {more && (
        <li className="px-2 pt-1.5 text-xs text-muted-foreground">{more.label}</li>
      )}
    </ul>
  )
}

// Keyed by repo id from the parent, so switching repositories remounts this and
// resets its state without a setState call inside an effect body.
function DiagramBody({ repoId }: { repoId: string }) {
  const [diagrams, setDiagrams] = useState<Diagrams | null>(null)
  const [status, setStatus] = useState("")
  const [partial, setPartial] = useState(false)
  const [progress, setProgress] = useState<DiagramProgress | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>

    // Poll while the backend still reports a partial (in-progress) preview and
    // stop as soon as indexing completes or the request starts failing.
    const poll = async () => {
      try {
        const res = await api.get(`/repos/${repoId}/diagrams`)
        if (cancelled) return
        setDiagrams(res.data.graphs ?? null)
        setStatus(res.data.status ?? "")
        setProgress(res.data.progress ?? null)
        setPartial(Boolean(res.data.partial))
        setError("")
        if (res.data.partial) timer = setTimeout(poll, POLL_INTERVAL_MS)
      } catch (err: any) {
        if (cancelled) return
        setError(
          err.response?.data?.detail || err.message || "Failed to load diagrams.",
        )
      }
    }

    poll()

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [repoId])

  if (error) {
    return (
      <div className="min-h-0 flex-1 p-6">
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Could not load architecture</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!diagrams) {
    return (
      <div className="relative min-h-0 flex-1">
        <Skeleton className="absolute inset-4 rounded-xl" />
      </div>
    )
  }

  const architecture = diagrams.directories
  const architectureGraph = architecture?.type === "tree" ? architecture : undefined
  const languages = diagrams.languages
  const languagePie = languages?.type === "pie" ? languages : undefined
  const entrypoints = diagrams.entrypoints
  const entrypointGraph = entrypoints?.type === "tree" ? entrypoints : undefined

  const percent =
    progress && progress.chunk_count > 0
      ? Math.min(100, Math.round((progress.embedded / progress.chunk_count) * 100))
      : null

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <div className="relative min-h-0 flex-1">
        {architectureGraph ? (
          <ArchitectureGraph graph={architectureGraph} />
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Nothing to show yet.
          </div>
        )}

        {/*
         * The build banner floats over the canvas rather than pushing it down,
         * so the diagram keeps the full height while it is being drawn.
         */}
        {partial && (
          <div className="absolute left-3 top-3 z-10 w-80 max-w-[calc(100%-1.5rem)] space-y-2.5 rounded-lg border bg-card/90 p-3 shadow-lg backdrop-blur">
            <div className="flex items-center gap-2.5 text-sm">
              <span className="relative flex size-2 flex-shrink-0">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/70 motion-reduce:animate-none" />
                <span className="relative inline-flex size-2 rounded-full bg-primary" />
              </span>
              <span className="text-muted-foreground">
                Building live — {progressText(status, progress)} Chat unlocks once
                this finishes.
              </span>
            </div>
            {percent !== null && (
              <div
                className="h-1 overflow-hidden rounded-full bg-muted"
                role="progressbar"
                aria-valuenow={percent}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Indexing ${percent}% complete`}
              >
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out motion-reduce:transition-none"
                  style={{ width: `${percent}%` }}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/*
       * Everything that is read rather than watched lives in the rail, and only
       * once the manifest is final: while indexing the canvas holds the whole
       * width, because a half-built language mix is just noise next to it.
       */}
      {!partial && (
        <aside className="reveal-rail flex w-72 flex-shrink-0 flex-col overflow-y-auto border-l bg-card/30">
          <RailSection title="Language mix">
            {languagePie ? (
              <LanguagePie graph={languagePie} size={200} stacked />
            ) : (
              <p className="text-sm text-muted-foreground">Nothing to show yet.</p>
            )}
          </RailSection>
          <div className="border-t" />
          <RailSection title="Entrypoints">
            <EntrypointList graph={entrypointGraph} />
          </RailSection>
        </aside>
      )}
    </div>
  )
}

/**
 * The repository's architecture: one full-height canvas with the directory tree,
 * and a rail for what supports it (language mix, entrypoints).
 *
 * The active repository is chosen in the shell header, so there is no picker
 * here; this view only has to know which repository to draw.
 */
export default function ArchitectureView({
  selectedRepoId,
}: {
  selectedRepoId: string
}) {
  if (!selectedRepoId) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="text-center text-muted-foreground">
          <p className="text-lg font-medium text-foreground">
            Select a repository to see its architecture
          </p>
          <p className="mt-1 text-sm">
            Diagrams are generated from the deterministic repository manifest.
          </p>
        </div>
      </div>
    )
  }

  return <DiagramBody key={selectedRepoId} repoId={selectedRepoId} />
}
