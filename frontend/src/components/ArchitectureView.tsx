import { useEffect, useState } from "react"
import { CircleAlertIcon } from "lucide-react"

import api from "../api/axiosConfig"
import ArchitectureGraph from "./ArchitectureGraph"
import LanguagePie from "./LanguagePie"
import type { PieGraph, TreeGraph } from "../lib/architecture"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

// The live preview polls while a repository is still indexing; the backend
// commits embedding progress per batch, so a coarse interval is plenty.
const POLL_INTERVAL_MS = 2000

type Diagrams = Record<string, TreeGraph | PieGraph>

const SECTIONS: { key: string; title: string }[] = [
  { key: "languages", title: "Language mix" },
  { key: "directories", title: "Directory map" },
  { key: "entrypoints", title: "Entrypoints" },
]

const STATUS_LABELS: Record<string, string> = {
  pending: "queued",
  cloning: "cloning",
  processing: "scanning files",
  embedding: "embedding",
}

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

function DiagramSection({
  title,
  graph,
}: {
  title: string
  graph?: TreeGraph | PieGraph
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!graph ? (
          <p className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground">
            Nothing to show yet.
          </p>
        ) : graph.type === "pie" ? (
          <LanguagePie graph={graph} />
        ) : (
          <ArchitectureGraph graph={graph} />
        )}
      </CardContent>
    </Card>
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
      <Alert variant="destructive">
        <CircleAlertIcon />
        <AlertTitle>Could not load architecture</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  if (!diagrams) {
    return (
      <div className="space-y-6">
        {SECTIONS.map((section) => (
          <div key={section.key} className="space-y-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-56 w-full rounded-xl" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {partial && (
        <div className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2 text-sm">
          <span className="relative flex size-2 flex-shrink-0">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/70 motion-reduce:animate-none" />
            <span className="relative inline-flex size-2 rounded-full bg-primary" />
          </span>
          <span className="text-muted-foreground">
            Live preview — {progressText(status, progress)} Files appear as they
            are indexed.
          </span>
        </div>
      )}
      {SECTIONS.map((section) => (
        <DiagramSection
          key={section.key}
          title={section.title}
          graph={diagrams[section.key]}
        />
      ))}
    </div>
  )
}

// In-progress repositories stay selectable so their architecture can be watched
// as it is built; a failed one cannot produce diagrams at all.
function repoOptionLabel(repo: any): string {
  if (repo.status === "embedding" && repo.chunk_count > 0) {
    const percent = Math.round(
      ((repo.embedded_count || 0) / repo.chunk_count) * 100,
    )
    return `${repo.full_name} — embedding ${percent}%`
  }
  const label = STATUS_LABELS[repo.status]
  return label ? `${repo.full_name} — ${label}` : repo.full_name
}

export default function ArchitectureView({
  repositories,
  selectedRepoId,
  setSelectedRepoId,
}: any) {
  const selectableRepos = repositories.filter(
    (repo: any) => repo.status !== "failed",
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="flex h-16 flex-shrink-0 items-center gap-3 border-b bg-card px-6">
        <label className="text-sm font-medium text-muted-foreground">
          Active context
        </label>
        <Select
          value={selectedRepoId ? String(selectedRepoId) : undefined}
          onValueChange={setSelectedRepoId}
        >
          <SelectTrigger className="h-9 w-full max-w-md">
            <SelectValue placeholder="Select a repository..." />
          </SelectTrigger>
          <SelectContent>
            {selectableRepos.map((repo: any) => (
              <SelectItem key={repo.id} value={String(repo.id)}>
                {repoOptionLabel(repo)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {selectedRepoId ? (
          <DiagramBody key={selectedRepoId} repoId={selectedRepoId} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
            <p className="text-lg font-medium text-foreground">
              Select a repository to see its architecture
            </p>
            <p className="text-sm">
              Diagrams are generated from the deterministic repository manifest.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
