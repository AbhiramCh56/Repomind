import { Badge } from "@/components/ui/badge"
import { STAGE_LABELS, type Repo } from "../lib/repos"

/**
 * One badge describing where a repository is in the import pipeline.
 *
 * Shared by the sidebar list and the shell header so both always agree about
 * what "Ready" means.
 */
export default function RepoStatusBadge({ repo }: { repo: Repo }) {
  if (repo.status === "failed") {
    return (
      <Badge variant="destructive" title={repo.error_message || undefined}>
        Failed
      </Badge>
    )
  }
  if (repo.status === "completed") {
    if (repo.is_queryable) {
      return (
        <Badge
          variant="outline"
          className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          title={
            repo.has_embeddings
              ? undefined
              : "No embedded code. Answers come from the repository manifest."
          }
        >
          Ready
        </Badge>
      )
    }
    return <Badge variant="destructive">Needs Re-import</Badge>
  }
  return (
    <Badge
      variant="outline"
      className="animate-pulse border-amber-500/30 bg-amber-500/10 text-amber-600 motion-reduce:animate-none dark:text-amber-400"
    >
      {STAGE_LABELS[repo.status] ?? "Processing..."}
    </Badge>
  )
}
