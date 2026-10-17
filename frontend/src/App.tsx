import { useRef, useState, useEffect } from "react"
import { toast } from "sonner"
import { Loader2Icon } from "lucide-react"

import api from "./api/axiosConfig"
import AuthView from "./components/AuthView"
import Sidebar from "./components/Sidebar"
import ChatInterface from "./components/ChatInterface"
import ArchitectureView from "./components/ArchitectureView"
import LandingView from "./components/landing/LandingView"
import OnboardingView from "./components/OnboardingView"
import RepoStatusBadge from "./components/RepoStatusBadge"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { isImporting, isRepoReady, repoOptionLabel, type Repo } from "./lib/repos"

// Backend origin for the few requests that bypass the axios instance: the SSE
// chat stream and the public /health probe (which lives outside /api/v1).
const API_ORIGIN = import.meta.env.VITE_API_URL || "http://localhost:8000"

// The row the delete confirmation dialog is currently acting on.
type PendingDelete = Repo | null

/** Neutral holding screen while the session or the repository list resolves. */
function BootScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Loader2Icon className="size-5 animate-spin text-muted-foreground motion-reduce:animate-none" />
    </div>
  )
}

export default function App() {
  const [email, setEmail] = useState("test@example.com")
  const [password, setPassword] = useState("password123")
  const [message, setMessage] = useState("")
  const [userProfile, setUserProfile] = useState(null)
  // A stored token means we must not paint the landing page before we know
  // whether it is still valid; hold the boot screen until the profile resolves.
  const [checkingAuth, setCheckingAuth] = useState(() =>
    Boolean(localStorage.getItem("access_token")),
  )

  const [repoUrl, setRepoUrl] = useState("")
  const [repositories, setRepositories] = useState<Repo[]>([])
  // Distinguishes "no repositories yet" from "repositories not fetched yet":
  // the first deserves the import screen, the second must never flash it.
  const [reposLoaded, setReposLoaded] = useState(false)
  const [isAddingRepo, setIsAddingRepo] = useState(false)
  const [selectedRepoId, setSelectedRepoId] = useState("")
  const [repoToDelete, setRepoToDelete] = useState<PendingDelete>(null)

  const [chatInput, setChatInput] = useState("")
  const [chatHistory, setChatHistory] = useState<
    { role: string; text: string }[]
  >([])
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null)
  const [isChatLoading, setIsChatLoading] = useState(false)

  const [chatEnabled, setChatEnabled] = useState(true)
  // The architecture is the product's front door, so that is where a session
  // opens; chat becomes selectable once the repository is indexed.
  const [activeView, setActiveView] = useState<"chat" | "architecture">(
    "architecture",
  )

  // Pre-login: the marketing landing page shows first; "Get Started" reveals the
  // sign-in form, and the auth screen can go back to the landing.
  const [authStarted, setAuthStarted] = useState(false)

  // The public health probe is the cheapest way to learn whether the backend
  // has chat gated off, so the UI can hide it instead of failing on send.
  useEffect(() => {
    fetch(`${API_ORIGIN}/health`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && typeof data.chat_enabled === "boolean") {
          setChatEnabled(data.chat_enabled)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (token) handleFetchProfile()
  }, [])

  // Load persisted chat history for the selected repository
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!selectedRepoId) {
        setChatHistory([])
        setCurrentSessionId(null)
        return
      }
      try {
        const sessionsRes = await api.get(`/chat/sessions/${selectedRepoId}`)
        if (cancelled) return
        const sessions = sessionsRes.data as { id: number }[]
        if (sessions.length === 0) {
          setCurrentSessionId(null)
          setChatHistory([])
          return
        }
        const sessionId = sessions[0].id // most recent session
        const msgsRes = await api.get(`/chat/sessions/${sessionId}/messages`)
        if (cancelled) return
        setCurrentSessionId(sessionId)
        setChatHistory(
          msgsRes.data.map((m: any) => ({
            role: m.role === "human" ? "user" : "assistant",
            text: m.content,
          })),
        )
      } catch (err: any) {
        console.error("Failed to load chat history", err)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [selectedRepoId])

  useEffect(() => {
    const isProcessing = repositories.some((repo) => isImporting(repo))
    let intervalId: any
    if (isProcessing && userProfile) {
      intervalId = setInterval(() => handleFetchRepos(), 2000)
    }
    return () => clearInterval(intervalId)
  }, [repositories, userProfile])

  const handleRegister = async () => {
    try {
      await api.post("/auth/register", { email, password })
      setMessage("Registered successfully! Logging you in...")
      handleLogin()
    } catch (err: any) {
      setMessage(
        `Registration Error: ${err.response?.data?.detail || err.message}`,
      )
    }
  }

  const handleLogin = async () => {
    try {
      const params = new URLSearchParams()
      params.append("username", email)
      params.append("password", password)
      const res = await api.post("/auth/login", params)
      localStorage.setItem("access_token", res.data.access_token)
      setMessage("")
      handleFetchProfile()
    } catch (err: any) {
      setMessage(`Login Error: ${err.response?.data?.detail || err.message}`)
    }
  }

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout")
    } catch (err) {
      console.error("Logout failed", err)
    } finally {
      localStorage.removeItem("access_token")
      setUserProfile(null)
      setRepositories([])
      setReposLoaded(false)
      setChatHistory([])
      setCurrentSessionId(null)
      setSelectedRepoId("")
    }
  }

  const handleFetchProfile = async () => {
    try {
      const res = await api.get("/auth/me")
      setUserProfile(res.data)
      handleFetchRepos()
    } catch (err: any) {
      console.error(err)
    } finally {
      setCheckingAuth(false)
    }
  }

  const handleFetchRepos = async () => {
    try {
      const res = await api.get("/repos/")
      const repos = res.data as Repo[]
      setRepositories(repos)
      setSelectedRepoId((prev) => {
        // Keep the current choice while it still exists — the list refetches on
        // every poll, and re-picking a repository mid-import would reset the
        // view underneath the user.
        if (prev && repos.some((repo) => String(repo.id) === String(prev))) {
          return prev
        }
        // Otherwise prefer a repository that is still importing: its
        // architecture can be watched being built, which is more useful than
        // jumping straight to an already-finished one.
        const importing = repos.find((repo) => isImporting(repo))
        if (importing) return String(importing.id)
        const ready = repos.find((repo) => isRepoReady(repo))
        if (ready) return String(ready.id)
        return repos[0] ? String(repos[0].id) : ""
      })
    } catch (err) {
      console.error(err)
    } finally {
      setReposLoaded(true)
    }
  }

  const handleAddRepo = async () => {
    if (!repoUrl.trim() || isAddingRepo) return
    setIsAddingRepo(true)
    try {
      const res = await api.post("/repos/", { github_url: repoUrl })
      setRepoUrl("")
      toast.success("Repository added. Building its architecture…")
      // Land on the new repository straight away: the architecture view can
      // show it being built live while the index runs.
      if (res.data?.id !== undefined) setSelectedRepoId(String(res.data.id))
      setActiveView("architecture")
      await handleFetchRepos()
    } catch (err: any) {
      toast.error(
        `Add repo failed: ${err.response?.data?.detail || err.message}`,
      )
    } finally {
      setIsAddingRepo(false)
    }
  }

  const handleDeleteRepo = async (repoId: string | number) => {
    try {
      await api.delete(`/repos/${repoId}`)
      if (String(selectedRepoId) === String(repoId)) setSelectedRepoId("")
      toast.success("Repository deleted.")
      handleFetchRepos()
    } catch (err: any) {
      toast.error(
        `Delete failed: ${err.response?.data?.detail || err.message}`,
      )
    }
  }

  const handleReprocessRepo = async (repoId: string | number) => {
    try {
      await api.post(`/repos/${repoId}/reprocess`)
      toast.success("Re-import started.")
      handleFetchRepos()
    } catch (err: any) {
      toast.error(
        `Re-import failed: ${err.response?.data?.detail || err.message}`,
      )
    }
  }

  const handleAskQuestion = async () => {
    if (!chatInput.trim() || !selectedRepoId) return
    const currentInput = chatInput
    const newHistory = [...chatHistory, { role: "user", text: currentInput }]

    setChatHistory([...newHistory, { role: "assistant", text: "" }])
    setChatInput("")
    setIsChatLoading(true)

    const applyAssistantText = (text: string) => {
      setChatHistory((prev) => {
        if (!prev.length || prev[prev.length - 1].role !== "assistant") return prev
        const copy = prev.slice()
        copy[copy.length - 1] = { role: "assistant", text }
        return copy
      })
    }

    try {
      const token = localStorage.getItem("access_token")
      const resp = await fetch(`${API_ORIGIN}/api/v1/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          repo_id: selectedRepoId,
          session_id: currentSessionId,
          message: currentInput,
        }),
      })

      if (!resp.ok || !resp.body) {
        const errBody = await resp.json().catch(() => null)
        throw new Error(errBody?.detail || resp.statusText)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let sepIndex
        while ((sepIndex = buffer.indexOf("\n\n")) >= 0) {
          const rawEvent = buffer.slice(0, sepIndex)
          buffer = buffer.slice(sepIndex + 2)

          for (const line of rawEvent.split("\n")) {
            if (!line.startsWith("data: ")) continue
            const data = JSON.parse(line.slice(6))
            if (data.error) throw new Error(data.error)
            if (data.text) applyAssistantText(data.text)
            if (data.session_id) setCurrentSessionId(data.session_id)
          }
        }
      }
    } catch (err: any) {
      applyAssistantText(
        `Error: ${err.response?.data?.detail || err.message}`,
      )
    } finally {
      setIsChatLoading(false)
    }
  }

  const selectableRepos = repositories.filter((repo) => repo.status !== "failed")
  const activeRepo =
    repositories.find((repo) => String(repo.id) === String(selectedRepoId)) ??
    null
  const repoReady = isRepoReady(activeRepo)
  // Chat needs both a server that offers it *and* a repository that has finished
  // indexing. Until then the effective view stays on the architecture, so the
  // user watches the build instead of typing into a box that cannot answer.
  const chatAvailable = chatEnabled && repoReady
  const view: "chat" | "architecture" =
    chatAvailable && activeView === "chat" ? "chat" : "architecture"
  const chatHint = !chatEnabled
    ? "Chat is temporarily unavailable."
    : !repoReady
      ? "Chat unlocks once this repository finishes indexing."
      : undefined

  // Announce the switch instead of silently enabling the chat tab. Only
  // repositories seen importing during this session qualify, so opening an
  // already-finished repository does not fire a toast.
  const seenImporting = useRef<Set<string>>(new Set())
  const announcedReady = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!activeRepo) return
    const id = String(activeRepo.id)
    if (isImporting(activeRepo)) {
      seenImporting.current.add(id)
      return
    }
    if (
      isRepoReady(activeRepo) &&
      seenImporting.current.has(id) &&
      !announcedReady.current.has(id)
    ) {
      announcedReady.current.add(id)
      seenImporting.current.delete(id)
      toast.success("Indexing complete — chat is ready.")
    }
  }, [activeRepo])

  if (checkingAuth) {
    return <BootScreen />
  }

  if (!userProfile) {
    if (!authStarted) {
      return <LandingView onGetStarted={() => setAuthStarted(true)} />
    }
    return (
      <AuthView
        email={email}
        setEmail={setEmail}
        password={password}
        setPassword={setPassword}
        handleLogin={handleLogin}
        handleRegister={handleRegister}
        message={message}
        onBack={() => setAuthStarted(false)}
      />
    )
  }

  // Repositories are still loading: showing the import screen here would flash
  // it at a user who already has one.
  if (!reposLoaded) {
    return <BootScreen />
  }

  // The first-run screen: no repositories, so importing one *is* the app.
  if (repositories.length === 0) {
    return (
      <OnboardingView
        repoUrl={repoUrl}
        setRepoUrl={setRepoUrl}
        onImport={handleAddRepo}
        importing={isAddingRepo}
        userProfile={userProfile}
        onLogout={handleLogout}
      />
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        userProfile={userProfile}
        repositories={repositories}
        selectedRepoId={selectedRepoId}
        onSelectRepo={setSelectedRepoId}
        repoUrl={repoUrl}
        setRepoUrl={setRepoUrl}
        handleAddRepo={handleAddRepo}
        handleReprocessRepo={handleReprocessRepo}
        handleRequestDelete={setRepoToDelete}
        handleLogout={handleLogout}
      />

      <Tabs
        value={view}
        onValueChange={(v) => setActiveView(v as "chat" | "architecture")}
        className="flex min-w-0 flex-1 flex-col gap-0"
      >
        {/*
         * One header for the whole workspace. The repository switcher used to
         * live in a second bar inside each view; keeping it here means the
         * active context is always visible and never duplicated.
         */}
        <header className="flex h-14 flex-shrink-0 items-center gap-3 border-b bg-card px-4">
          <TabsList>
            <TabsTrigger value="chat" disabled={!chatAvailable} title={chatHint}>
              Chat
            </TabsTrigger>
            <TabsTrigger value="architecture">Architecture</TabsTrigger>
          </TabsList>

          <div className="ml-auto flex min-w-0 items-center gap-3">
            {activeRepo && (
              <span className="hidden sm:inline-flex">
                <RepoStatusBadge repo={activeRepo} />
              </span>
            )}
            <Select
              value={selectedRepoId || undefined}
              onValueChange={setSelectedRepoId}
            >
              <SelectTrigger
                className="h-8 w-full max-w-xs"
                aria-label="Active repository"
              >
                <SelectValue placeholder="Select a repository" />
              </SelectTrigger>
              <SelectContent>
                {selectableRepos.map((repo) => (
                  <SelectItem key={repo.id} value={String(repo.id)}>
                    {repoOptionLabel(repo)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          {view === "chat" ? (
            <ChatInterface
              selectedRepoId={selectedRepoId}
              chatHistory={chatHistory}
              chatInput={chatInput}
              setChatInput={setChatInput}
              handleAskQuestion={handleAskQuestion}
              isChatLoading={isChatLoading}
            />
          ) : (
            <ArchitectureView selectedRepoId={selectedRepoId} />
          )}
        </div>
      </Tabs>

      <AlertDialog
        open={Boolean(repoToDelete)}
        onOpenChange={(open) => {
          if (!open) setRepoToDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete repository?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes{" "}
              <span className="font-medium text-foreground">
                {repoToDelete?.name}
              </span>{" "}
              and everything indexed for it. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const id = repoToDelete?.id
                setRepoToDelete(null)
                if (id) handleDeleteRepo(id)
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
