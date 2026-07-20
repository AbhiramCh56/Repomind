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
    } catch (err: any) {
      setMessage(
        `Fetch Repos Error: ${err.response?.data?.detail || err.message}`,
      );
    }
  };

  return (
    <div
      style={{
        padding: "2rem",
        fontFamily: "sans-serif",
        maxWidth: "600px",
        margin: "0 auto",
      }}
    >
      <h1>RepoMind AI - Auth & Repo Test</h1>
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
          {repositories.map((repo) => (
            <div key={repo.id}>
              {repo.full_name} - {repo.status}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
