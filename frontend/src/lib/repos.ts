/**
 * Repository metadata shared by the shell, the sidebar and the diagram view.
 *
 * The backend returns these fields on every `/repos/` row, so the helpers here
 * are the single place that decides what "still importing" and "ready to ask
 * questions" mean.
 */

export interface Repo {
  id: string | number
  name: string
  full_name: string
  status: string
  is_queryable?: boolean
  has_embeddings?: boolean
  error_message?: string | null
  chunk_count?: number
  embedded_count?: number
}

/** Every status that means the backend is still working on the repository. */
export const IN_PROGRESS_STATUSES = ["pending", "cloning", "processing", "embedding"]

/** Human-readable label for each in-flight pipeline stage. */
export const STAGE_LABELS: Record<string, string> = {
  pending: "Queued",
  cloning: "Cloning",
  processing: "Parsing code",
  embedding: "Building index",
}

export function isImporting(repo: Repo | null | undefined): boolean {
  return Boolean(repo && IN_PROGRESS_STATUSES.includes(repo.status))
}

/**
 * A repository can answer questions once the pipeline has finished *and* the
 * backend marks it queryable.
 *
 * `is_queryable`, never `has_embeddings`, is the gate: a docs/config-only
 * repository legitimately has no vectors, so a `has_embeddings` check would
 * lock chat out of a perfectly good repository.
 */
export function isRepoReady(repo: Repo | null | undefined): boolean {
  return Boolean(repo && repo.status === "completed" && repo.is_queryable)
}

/** Embedding progress as a 0–100 percentage, or null when it cannot be known. */
export function embeddingPercent(repo: Repo): number | null {
  const total = repo.chunk_count ?? 0
  if (repo.status !== "embedding" || total <= 0) return null
  return Math.min(100, Math.round(((repo.embedded_count ?? 0) / total) * 100))
}

/** Dropdown label that surfaces an in-flight stage, so the switcher explains itself. */
export function repoOptionLabel(repo: Repo): string {
  const percent = embeddingPercent(repo)
  if (percent !== null) return `${repo.full_name} — embedding ${percent}%`
  const label = STAGE_LABELS[repo.status]
  return label ? `${repo.full_name} — ${label}` : repo.full_name
}
