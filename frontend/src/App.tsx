import { useState, useEffect } from "react";
import api from "./api/axiosConfig";
import AuthView from "./components/AuthView";
import Sidebar from "./components/Sidebar";
import ChatInterface from "./components/ChatInterface";

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
  const [isChatLoading, setIsChatLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) handleFetchProfile();
  }, []);

  useEffect(() => {
    const isProcessing = repositories.some(
      (repo) => repo.status === "pending" || repo.status === "cloning",
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
            (r: any) => r.status === "completed" && r.has_embeddings,
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

    setChatHistory(newHistory);
    setChatInput("");
    setIsChatLoading(true);

    try {
      const res = await api.post("/chat/", {
        repository_id: selectedRepoId,
        question: currentInput,
      });
      setChatHistory([
        ...newHistory,
        { role: "assistant", text: res.data.answer },
      ]);
    } catch (err: any) {
      setChatHistory([
        ...newHistory,
        {
          role: "assistant",
          text: `Error: ${err.response?.data?.detail || err.message}`,
        },
      ]);
    } finally {
      setIsChatLoading(false);
    }
  };

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
    </div>
  );
}
