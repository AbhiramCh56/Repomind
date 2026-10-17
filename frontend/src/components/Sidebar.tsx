import {
  ChevronUpIcon,
  FolderGit2Icon,
  LogOutIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// Human-readable label for each in-flight pipeline stage reported by the API.
const STAGE_LABELS: Record<string, string> = {
  pending: "Queued",
  cloning: "Cloning",
  processing: "Parsing code",
  embedding: "Building index",
}

function StatusBadge({ repo }: { repo: any }) {
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

export default function Sidebar({
  userProfile,
  repositories,
  repoUrl,
  setRepoUrl,
  handleAddRepo,
  handleReprocessRepo,
  handleRequestDelete,
  handleLogout,
}: any) {
  return (
    <aside className="flex w-80 flex-shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-3 p-5">
        <div className="flex size-9 flex-shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <FolderGit2Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <h2 className="truncate font-heading text-base font-semibold leading-tight">
            RepoMind AI
          </h2>
          <p className="truncate text-xs text-muted-foreground">
            {userProfile?.email}
          </p>
        </div>
      </div>

      <Separator />

      <div className="space-y-3 px-4 py-4">
        <Label
          htmlFor="repo-url"
          className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
        >
          Import repository
        </Label>
        <Input
          id="repo-url"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="https://github.com/..."
          className="h-9"
        />
        <Button
          className="w-full"
          onClick={handleAddRepo}
          disabled={!repoUrl.trim()}
        >
          <PlusIcon />
          Add to workspace
        </Button>
      </div>

      <Separator />

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="px-4 pb-3 pt-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Your repositories
        </h3>
        <ScrollArea className="flex-1">
          <div className="px-4 pb-4">
            {repositories.length === 0 ? (
              <p className="text-sm italic text-muted-foreground">
                No repositories imported yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {repositories.map((repo: any) => (
                  <li
                    key={repo.id}
                    className="rounded-lg border bg-card p-3 text-card-foreground shadow-xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div
                          className="truncate text-sm font-medium"
                          title={repo.full_name}
                        >
                          {repo.name}
                        </div>
                        <div
                          className="mt-0.5 truncate text-xs text-muted-foreground"
                          title={repo.full_name}
                        >
                          {repo.full_name}
                        </div>
                      </div>

                      <div className="flex flex-shrink-0 items-center gap-0.5">
                        {(!repo.is_queryable || repo.status === "failed") && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-xs"
                                aria-label="Re-import repository"
                                onClick={() => handleReprocessRepo(repo.id)}
                              >
                                <RefreshCwIcon />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Re-import</TooltipContent>
                          </Tooltip>
                        )}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              className="text-muted-foreground hover:text-destructive"
                              aria-label={`Delete ${repo.name}`}
                              onClick={() => handleRequestDelete(repo)}
                            >
                              <Trash2Icon />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Delete</TooltipContent>
                        </Tooltip>
                      </div>
                    </div>

                    <div className="mt-2.5">
                      <StatusBadge repo={repo} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </ScrollArea>
      </div>

      <Separator />

      <div className="p-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="h-auto w-full justify-start gap-2 px-2 py-2"
            >
              <span className="flex size-7 flex-shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                {(userProfile?.email?.[0] ?? "U").toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate text-left text-sm">
                {userProfile?.email}
              </span>
              <ChevronUpIcon className="size-4 flex-shrink-0 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel className="truncate">
              {userProfile?.email}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={handleLogout}>
              <LogOutIcon />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  )
}
