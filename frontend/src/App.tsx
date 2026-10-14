import { useState, useEffect } from "react";
import api from "./api/axiosConfig";
import AuthView from "./components/AuthView";
import Sidebar from "./components/Sidebar";
import ChatInterface from "./components/ChatInterface";
import ArchitectureView from "./components/ArchitectureView";

// Backend origin for the few requests that bypass the axios instance: the SSE
// chat stream and the public /health probe (which lives outside /api/v1).
const API_ORIGIN = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Every status that means the backend is still working on the repository.
// Polling must cover all of them, otherwise the UI freezes mid-import.
const IN_PROGRESS_STATUSES = [
  "pending",
  "cloning",
  "processing",
  "embedding",
];

export default function App() {
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("password123");
  const [message, setMessage] = useState("");
  const [userProfile, setUserProfile] = useState(null);

  const [repoUrl, setRepoUrl] = useState("");
  const [repositories, setRepositories] = useState<any[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState("");

  const [chatInput, setChatInput] = useState("");
  const [chatHistory, setChatHistory] = useState<
    { role: string; text: string }[]
  >([]);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);

  const [chatEnabled, setChatEnabled] = useState(true);
  const [activeView, setActiveView] = useState<"chat" | "architecture">("chat");

  // The public health probe is the cheapest way to learn whether the backend
  // has chat gated off, so the UI can hide it instead of failing on send.
  useEffect(() => {
    fetch(`${API_ORIGIN}/health`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && typeof data.chat_enabled === "boolean") {
          setChatEnabled(data.chat_enabled);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) handleFetchProfile();
  }, []);

  // Load persisted chat history for the selected repository
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!selectedRepoId) {
        setChatHistory([]);
        setCurrentSessionId(null);
        return;
      }
      try {
        const sessionsRes = await api.get(`/chat/sessions/${selectedRepoId}`);
        if (cancelled) return;
        const sessions = sessionsRes.data as { id: number }[];
        if (sessions.length === 0) {
          setCurrentSessionId(null);
          setChatHistory([]);
          return;
        }
        const sessionId = sessions[0].id; // most recent session
        const msgsRes = await api.get(`/chat/sessions/${sessionId}/messages`);
        if (cancelled) return;
        setCurrentSessionId(sessionId);
        setChatHistory(
          msgsRes.data.map((m: any) => ({
            role: m.role === "human" ? "user" : "assistant",
            text: m.content,
          })),
        );
      } catch (err: any) {
        console.error("Failed to load chat history", err);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [selectedRepoId]);

  useEffect(() => {
    const isProcessing = repositories.some((repo: any) =>
      IN_PROGRESS_STATUSES.includes(repo.status),
    );
    let intervalId: any;
    if (isProcessing && userProfile) {
      intervalId = setInterval(() => handleFetchRepos(), 2000);
    }
    return () => clearInterval(intervalId);
  }, [repositories, userProfile]);

  const handleRegister = async () => {
    try {
      await api.post("/auth/register", { email, password });
      setMessage("Registered successfully! Logging you in...");
      handleLogin();
    } catch (err: any) {
      setMessage(
        `Registration Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleLogin = async () => {
    try {
      const params = new URLSearchParams();
      params.append("username", email);
      params.append("password", password);
      const res = await api.post("/auth/login", params);
      localStorage.setItem("access_token", res.data.access_token);
      setMessage("");
      handleFetchProfile();
    } catch (err: any) {
      setMessage(`Login Error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (err) {
      console.error("Logout failed", err);
    } finally {
      localStorage.removeItem("access_token");
      setUserProfile(null);
      setRepositories([]);
      setChatHistory([]);
      setCurrentSessionId(null);
      setSelectedRepoId("");
    }
  };

  const handleFetchProfile = async () => {
    try {
      const res = await api.get("/auth/me");
      setUserProfile(res.data);
      handleFetchRepos();
    } catch (err: any) {
      console.error(err);
    }
  };

  const handleFetchRepos = async () => {
    try {
      const res = await api.get("/repos/");
      setRepositories(res.data);
      setSelectedRepoId((prev) => {
        if (!prev && res.data.length > 0) {
          const firstValid = res.data.find(
            (r: any) => r.status === "completed" && r.is_queryable,
          );
          return firstValid ? firstValid.id : prev;
        }
        return prev;
      });
    } catch (err: any) {
      console.error(err);
    }
  };

  const handleAddRepo = async () => {
    if (!repoUrl) return;
    try {
      await api.post("/repos/", { github_url: repoUrl });
      setRepoUrl("");
      handleFetchRepos();
    } catch (err: any) {
      alert(`Add Repo Error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleDeleteRepo = async (repoId: string) => {
    if (!window.confirm("Are you sure you want to delete this repository?"))
      return;
    try {
      await api.delete(`/repos/${repoId}`);
      if (selectedRepoId === repoId) setSelectedRepoId("");
      handleFetchRepos();
    } catch (err: any) {
      alert(`Delete Error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleReprocessRepo = async (repoId: string) => {
    try {
      await api.post(`/repos/${repoId}/reprocess`);
      handleFetchRepos();
    } catch (err: any) {
      alert(`Reprocess Error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleAskQuestion = async () => {
    if (!chatInput.trim() || !selectedRepoId) return;
    const currentInput = chatInput;
    const newHistory = [...chatHistory, { role: "user", text: currentInput }];

    setChatHistory([...newHistory, { role: "assistant", text: "" }]);
    setChatInput("");
    setIsChatLoading(true);

    const applyAssistantText = (text: string) => {
      setChatHistory((prev) => {
        if (!prev.length || prev[prev.length - 1].role !== "assistant") return prev;
        const copy = prev.slice();
        copy[copy.length - 1] = { role: "assistant", text };
        return copy;
      });
    };

    try {
      const token = localStorage.getItem("access_token");
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
      });

      if (!resp.ok || !resp.body) {
        const errBody = await resp.json().catch(() => null);
        throw new Error(errBody?.detail || resp.statusText);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sepIndex;
        while ((sepIndex = buffer.indexOf("\n\n")) >= 0) {
          const rawEvent = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + 2);

          for (const line of rawEvent.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const data = JSON.parse(line.slice(6));
            if (data.error) throw new Error(data.error);
            if (data.text) applyAssistantText(data.text);
            if (data.session_id) setCurrentSessionId(data.session_id);
          }
        }
      }
    } catch (err: any) {
      applyAssistantText(
        `Error: ${err.response?.data?.detail || err.message}`,
      );
    } finally {
      setIsChatLoading(false);
    }
  };

  // Never leave the user stranded on a tab that is switched off server-side:
  // when chat is gated off, the effective view is always architecture.
  const view = chatEnabled ? activeView : "architecture";

  if (!userProfile) {
    return (
      <>
        <AuthView
          email={email}
          setEmail={setEmail}
          password={password}
          setPassword={setPassword}
          handleLogin={handleLogin}
          handleRegister={handleRegister}
          message={message}
        />
      </>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        userProfile={userProfile}
        repositories={repositories}
        repoUrl={repoUrl}
        setRepoUrl={setRepoUrl}
        handleAddRepo={handleAddRepo}
        handleReprocessRepo={handleReprocessRepo}
        handleDeleteRepo={handleDeleteRepo}
        handleLogout={handleLogout}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <div className="h-12 border-b border-gray-200 bg-white flex items-center gap-2 px-4 flex-shrink-0">
          <button
            onClick={() => setActiveView("chat")}
            disabled={!chatEnabled}
            title={chatEnabled ? undefined : "Chat is temporarily unavailable."}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              view === "chat"
                ? "bg-blue-600 text-white"
                : "text-gray-600 hover:bg-gray-100"
            } ${chatEnabled ? "" : "opacity-50 cursor-not-allowed hover:bg-transparent"}`}
          >
            Chat
          </button>
          <button
            onClick={() => setActiveView("architecture")}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              view === "architecture"
                ? "bg-blue-600 text-white"
                : "text-gray-600 hover:bg-gray-100"
            }`}
          >
            Architecture
          </button>
          {!chatEnabled && (
            <span className="ml-auto text-xs text-gray-500">
              Chat is temporarily unavailable.
            </span>
          )}
        </div>
        <div className="flex-1 min-h-0 flex">
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
      </div>
    </div>
  );
}
