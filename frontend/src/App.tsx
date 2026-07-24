import { useState, useEffect } from "react";
import axios from "axios";

// API Instance
const api = axios.create({
  baseURL: "http://localhost:8000/api/v1",
  withCredentials: true,
});

// 1. Request Interceptor: Automatically attach the access token to all requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 2. Response Interceptor: Handle 401 errors and automatically refresh token
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    // If we get a 401 and haven't retried this specific request yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        // Use a clean axios instance to avoid infinite loops on the refresh endpoint
        const { data } = await axios.post(
          "http://localhost:8000/api/v1/auth/refresh",
          {},
          { withCredentials: true },
        );
        // Save the new token
        localStorage.setItem("access_token", data.access_token);
        // Update the original request with the new token and retry it
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return api(originalRequest);
      } catch (refreshError) {
        console.error("Refresh token expired or invalid");
        // In a real app, you would redirect to /login here
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  },
);

export default function App() {
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("password123");
  const [message, setMessage] = useState(
    "Welcome! Please interact with the API.",
  );
  const [userProfile, setUserProfile] = useState<any>(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [repositories, setRepositories] = useState<any[]>([]);

  // Chat State
  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatHistory, setChatHistory] = useState<
    { role: string; text: string }[]
  >([]);
  const [isChatLoading, setIsChatLoading] = useState(false);

  useEffect(() => {
    // Check if any repo is currently processing
    const isProcessing = repositories.some(
      (repo) => repo.status === "pending" || repo.status === "cloning",
    );

    let intervalId: any;

    // If something is processing, start polling every 2 seconds
    if (isProcessing && userProfile) {
      intervalId = setInterval(() => {
        handleFetchRepos();
      }, 2000);
    }

    // Cleanup the interval when the component unmounts or processing finishes
    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [repositories, userProfile]);

  const handleRegister = async () => {
    try {
      await api.post("/auth/register", { email, password });
      setMessage("Registered successfully! Now try logging in.");
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
      setMessage("Logged in successfully!");
      handleFetchProfile();
    } catch (err: any) {
      setMessage(`Login Error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const handleFetchProfile = async () => {
    try {
      // Look ma, no manual headers! The interceptor handles it now.
      const res = await api.get("/auth/me");
      setUserProfile(res.data);
      handleFetchRepos();
    } catch (err: any) {
      setMessage(
        `Fetch Profile Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleAddRepo = async () => {
    try {
      setMessage("Submitting repository...");
      await api.post("/repos/", { github_url: repoUrl });
      setMessage("Repository submitted!");
      setRepoUrl("");
      handleFetchRepos();
    } catch (err: any) {
      setMessage(
        `Add Repo Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleFetchRepos = async () => {
    try {
      const res = await api.get("/repos/");
      setRepositories(res.data);
      // Auto-select the first completed repo if none is selected
      if (!selectedRepoId && res.data.length > 0) {
        const firstCompleted = res.data.find(
          (r: any) => r.status === "completed" && r.has_embeddings,
        );
        if (firstCompleted) {
          setSelectedRepoId(firstCompleted.id);
        }
      }
    } catch (err: any) {
      setMessage(
        `Fetch Repos Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleDeleteRepo = async (repoId: string) => {
    try {
      await api.delete(`/repos/${repoId}`);
      setMessage("Repository deleted successfully.");
      if (selectedRepoId === repoId) setSelectedRepoId("");
      handleFetchRepos();
    } catch (err: any) {
      setMessage(
        `Delete Repo Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleReprocessRepo = async (repoId: string) => {
    try {
      await api.post(`/repos/${repoId}/reprocess`);
      setMessage("Repository re-import started...");
      handleFetchRepos();
    } catch (err: any) {
      setMessage(
        `Reprocess Repo Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  const handleAskQuestion = async () => {
    if (!chatInput.trim() || !selectedRepoId) return;

    const newHistory = [...chatHistory, { role: "user", text: chatInput }];
    setChatHistory(newHistory);
    setChatInput("");
    setIsChatLoading(true);

    try {
      const res = await api.post("/chat/", {
        repository_id: selectedRepoId,
        question: chatInput,
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

  return (
    <div
      style={{
        padding: "2rem",
        fontFamily: "sans-serif",
        maxWidth: "800px",
        margin: "0 auto",
        display: "flex",
        gap: "2rem",
      }}
    >
      {/* Left Column: Auth & Repos */}
      <div style={{ flex: 1 }}>
        <h1>RepoMind AI - Workspace</h1>
        <div
          style={{
            marginBottom: "1rem",
            padding: "1rem",
            background: "#f0f0f0",
            borderRadius: "8px",
          }}
        >
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
          />
          <br />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
          />
          <br />
          <button onClick={handleRegister}>Register</button>
          <button onClick={handleLogin}>Login</button>
        </div>
        <p>{message}</p>
        {userProfile && (
          <div
            style={{
              marginTop: "20px",
              padding: "1rem",
              background: "#e0ffe0",
              borderRadius: "8px",
            }}
          >
            <h3>Profile</h3>
            <pre>{JSON.stringify(userProfile, null, 2)}</pre>
            <h3>Repositories</h3>
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="GitHub URL"
            />
            <button onClick={handleAddRepo}>Import</button>
            <button onClick={handleFetchRepos}>Refresh List</button>
            <ul style={{ paddingLeft: "20px" }}>
              {repositories.map((repo) => (
                <li key={repo.id} style={{ marginBottom: "10px" }}>
                  <strong>{repo.full_name}</strong> - {repo.status}
                  {repo.status === "completed" && !repo.has_embeddings && (
                    <span
                      style={{
                        color: "#d9534f",
                        marginLeft: "10px",
                        fontSize: "0.85em",
                        fontWeight: "bold",
                      }}
                    >
                      (No Embeddings - Reprocess Required)
                    </span>
                  )}
                  <br />
                  <button
                    onClick={() => handleReprocessRepo(repo.id)}
                    style={{
                      marginRight: "5px",
                      fontSize: "12px",
                      marginTop: "4px",
                    }}
                  >
                    Re-import
                  </button>
                  <button
                    onClick={() => handleDeleteRepo(repo.id)}
                    style={{
                      fontSize: "12px",
                      color: "#d9534f",
                      marginTop: "4px",
                    }}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Right Column: Chat Interface */}
      {userProfile && (
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            background: "#f9f9f9",
            borderRadius: "8px",
            padding: "1rem",
            border: "1px solid #ccc",
          }}
        >
          <h3>Chat with Repository</h3>

          <div style={{ marginBottom: "10px" }}>
            <label>Select Repo: </label>
            <select
              value={selectedRepoId}
              onChange={(e) => setSelectedRepoId(e.target.value)}
              style={{ width: "100%", padding: "5px" }}
            >
              <option value="" disabled>
                Select a repository...
              </option>
              {repositories
                .filter((r) => r.status === "completed" && r.has_embeddings)
                .map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.full_name}
                  </option>
                ))}
            </select>
          </div>

          <div
            style={{
              flex: 1,
              overflowY: "auto",
              background: "#fff",
              border: "1px solid #ddd",
              borderRadius: "4px",
              padding: "10px",
              marginBottom: "10px",
              minHeight: "300px",
            }}
          >
            {chatHistory.length === 0 ? (
              <p style={{ color: "#888", textAlign: "center" }}>
                Ask a question about the codebase!
              </p>
            ) : (
              chatHistory.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    marginBottom: "10px",
                    textAlign: msg.role === "user" ? "right" : "left",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      padding: "8px 12px",
                      borderRadius: "16px",
                      background: msg.role === "user" ? "#007bff" : "#e9ecef",
                      color: msg.role === "user" ? "#fff" : "#000",
                      maxWidth: "80%",
                      wordBreak: "break-word",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {msg.text}
                  </span>
                </div>
              ))
            )}
            {isChatLoading && (
              <div style={{ textAlign: "left", color: "#888" }}>
                Thinking...
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: "10px" }}>
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyPress={(e) => e.key === "Enter" && handleAskQuestion()}
              placeholder="E.g., What does main.py do?"
              style={{ flex: 1, padding: "8px" }}
              disabled={!selectedRepoId || isChatLoading}
            />
            <button
              onClick={handleAskQuestion}
              disabled={!selectedRepoId || isChatLoading || !chatInput.trim()}
              style={{ padding: "8px 16px", cursor: "pointer" }}
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
