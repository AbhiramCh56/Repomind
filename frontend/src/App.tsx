import { useState, useEffect } from "react"
import { toast } from "sonner"

import api from "./api/axiosConfig"
import AuthView from "./components/AuthView"
import Sidebar from "./components/Sidebar"
import ChatInterface from "./components/ChatInterface"
import ArchitectureView from "./components/ArchitectureView"
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

// Backend origin for the few requests that bypass the axios instance: the SSE
// chat stream and the public /health probe (which lives outside /api/v1).
const API_ORIGIN = import.meta.env.VITE_API_URL || "http://localhost:8000"

// Every status that means the backend is still working on the repository.
// Polling must cover all of them, otherwise the UI freezes mid-import.
const IN_PROGRESS_STATUSES = [
  "pending",
  "cloning",
  "processing",
  "embedding",
]

// The row the delete confirmation dialog is currently acting on.
type PendingDelete = { id: string | number; name: string } | null

export default function App() {
  const [email, setEmail] = useState("test@example.com")
  const [password, setPassword] = useState("password123")
  const [message, setMessage] = useState("")
  const [userProfile, setUserProfile] = useState(null)

  const [repoUrl, setRepoUrl] = useState("")
  const [repositories, setRepositories] = useState<any[]>([])
  const [selectedRepoId, setSelectedRepoId] = useState("")
  const [repoToDelete, setRepoToDelete] = useState<PendingDelete>(null)

  const [chatInput, setChatInput] = useState("")
  const [chatHistory, setChatHistory] = useState<
    { role: string; text: string }[]
  >([])
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null)
  const [isChatLoading, setIsChatLoading] = useState(false)

  const [chatEnabled, setChatEnabled] = useState(true)
  const [activeView, setActiveView] = useState<"chat" | "architecture">("chat")

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
    const isProcessing = repositories.some((repo: any) =>
      IN_PROGRESS_STATUSES.includes(repo.status),
    )
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
    }
  }

  const handleFetchRepos = async () => {
    try {
      const res = await api.get("/repos/")
      setRepositories(res.data)
      setSelectedRepoId((prev) => {
        if (prev) return prev
        // Prefer a repository that is still importing: the architecture view
        // can show it being built live, which is more useful than jumping to an
        // already-finished one.
        const importing = res.data.find((r: any) =>
          IN_PROGRESS_STATUSES.includes(r.status),
        )
        if (importing) return importing.id
        const firstValid = res.data.find(
          (r: any) => r.status === "completed" && r.is_queryable,
        )
        return firstValid ? firstValid.id : prev
      })
    } catch (err: any) {
      console.error(err)
    }
  }

  const handleAddRepo = async () => {
    if (!repoUrl) return
    try {
      await api.post("/repos/", { github_url: repoUrl })
      setRepoUrl("")
      toast.success("Repository added to your workspace.")
      handleFetchRepos()
    } catch (err: any) {
      toast.error(
        `Add repo failed: ${err.response?.data?.detail || err.message}`,
      )
    }
  }

  const handleDeleteRepo = async (repoId: string | number) => {
    try {
      await api.delete(`/repos/${repoId}`)
      if (selectedRepoId === repoId) setSelectedRepoId("")
      toast.success("Repository deleted.")
      handleFetchRepos()
    } catch (err: any) {
      toast.error(
        `Delete failed: ${err.response?.data?.detail || err.message}`,
      )
    }
  }

  const handleReprocessRepo = async (repoId: string) => {
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

  // Never leave the user stranded on a tab that is switched off server-side:
  // when chat is gated off, the effective view is always architecture.
  const view = chatEnabled ? activeView : "architecture"

  if (!userProfile) {
    return (
      <AuthView
        email={email}
        setEmail={setEmail}
        password={password}
        setPassword={setPassword}
        handleLogin={handleLogin}
        handleRegister={handleRegister}
        message={message}
      />
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        userProfile={userProfile}
        repositories={repositories}
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
        <header className="flex h-14 flex-shrink-0 items-center gap-3 border-b bg-card px-4">
          <TabsList>
            <TabsTrigger
              value="chat"
              disabled={!chatEnabled}
              title={chatEnabled ? undefined : "Chat is temporarily unavailable."}
            >
              Chat
            </TabsTrigger>
            <TabsTrigger value="architecture">Architecture</TabsTrigger>
          </TabsList>

          <div className="ml-auto flex items-center gap-2">
            {!chatEnabled && (
              <span className="hidden text-xs text-muted-foreground sm:inline">
                Chat is temporarily unavailable.
              </span>
            )}
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          {view === "chat" ? (
            <ChatInterface
              repositories={repositories}
              selectedRepoId={selectedRepoId}
              setSelectedRepoId={setSelectedRepoId}
              chatHistory={chatHistory}
              chatInput={chatInput}
              setChatInput={setChatInput}
              handleAskQuestion={handleAskQuestion}
              isChatLoading={isChatLoading}
            />
          ) : (
            <ArchitectureView
              repositories={repositories}
              selectedRepoId={selectedRepoId}
              setSelectedRepoId={setSelectedRepoId}
            />
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
