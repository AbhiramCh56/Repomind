import { useEffect, useState } from "react";
import api from "../api/axiosConfig";
import ArchitectureGraph from "./ArchitectureGraph";
import LanguagePie from "./LanguagePie";
import type { PieGraph, TreeGraph } from "../lib/architecture";

// The live preview polls while a repository is still indexing; the backend
// commits embedding progress per batch, so a coarse interval is plenty.
const POLL_INTERVAL_MS = 2000;

type Diagrams = Record<string, TreeGraph | PieGraph>;

const SECTIONS: { key: string; title: string }[] = [
  { key: "languages", title: "Language mix" },
  { key: "directories", title: "Directory map" },
  { key: "entrypoints", title: "Entrypoints" },
];

const STATUS_LABELS: Record<string, string> = {
  pending: "queued",
  cloning: "cloning",
  processing: "scanning files",
  embedding: "embedding",
};

type DiagramProgress = {
  embedded: number;
  chunk_count: number;
  live_files: number;
  total_files: number;
};

function progressText(status: string, progress: DiagramProgress | null): string {
  if (status === "cloning") return "Cloning the repository…";
  if (status === "processing") {
    const files = progress ? `${progress.live_files}/${progress.total_files}` : "0/0";
    return `Scanning files — ${files} files identified.`;
  }
  if (status === "embedding" && progress) {
    return `${progress.embedded}/${progress.chunk_count} chunks embedded.`;
  }
  if (progress) {
    return `${progress.embedded}/${progress.chunk_count} chunks embedded.`;
  }
  return "Updating as indexing progresses.";
}

function DiagramSection({ title, graph }: { title: string; graph?: TreeGraph | PieGraph }) {
  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
        {title}
      </h2>
      {!graph ? (
        <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded-lg p-4">
          Nothing to show yet.
        </p>
      ) : graph.type === "pie" ? (
        <LanguagePie graph={graph} />
      ) : (
        <ArchitectureGraph graph={graph} />
      )}
    </section>
  );
}

// Keyed by repo id from the parent, so switching repositories remounts this and
// resets its state without a setState call inside an effect body.
function DiagramBody({ repoId }: { repoId: string }) {
  const [diagrams, setDiagrams] = useState<Diagrams | null>(null);
  const [status, setStatus] = useState("");
  const [partial, setPartial] = useState(false);
  const [progress, setProgress] = useState<DiagramProgress | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    // Poll while the backend still reports a partial (in-progress) preview and
    // stop as soon as indexing completes or the request starts failing.
    const poll = async () => {
      try {
        const res = await api.get(`/repos/${repoId}/diagrams`);
        if (cancelled) return;
        setDiagrams(res.data.graphs ?? null);
        setStatus(res.data.status ?? "");
        setProgress(res.data.progress ?? null);
        setPartial(Boolean(res.data.partial));
        setError("");
        if (res.data.partial) timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err: any) {
        if (cancelled) return;
        setError(
          err.response?.data?.detail || err.message || "Failed to load diagrams.",
        );
      }
    };

    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [repoId]);

  if (error) {
    return (
      <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">
        {error}
      </p>
    );
  }

  if (!diagrams) {
    return <p className="text-sm text-gray-500">Loading architecture...</p>;
  }

  return (
    <>
      {partial && (
        <p className="flex items-center gap-2 text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-lg p-3">
          <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          Live preview — {progressText(status, progress)} Files appear as they are
          indexed.
        </p>
      )}
      {SECTIONS.map((section) => (
        <DiagramSection
          key={section.key}
          title={section.title}
          graph={diagrams[section.key]}
        />
      ))}
    </>
  );
}

// In-progress repositories stay selectable so their architecture can be watched
// as it is built; a failed one cannot produce diagrams at all.
function repoOptionLabel(repo: any): string {
  if (repo.status === "embedding" && repo.chunk_count > 0) {
    const percent = Math.round(
      ((repo.embedded_count || 0) / repo.chunk_count) * 100,
    );
    return `${repo.full_name} — embedding ${percent}%`;
  }
  const label = STATUS_LABELS[repo.status];
  return label ? `${repo.full_name} — ${label}` : repo.full_name;
}

export default function ArchitectureView({
  repositories,
  selectedRepoId,
  setSelectedRepoId,
}: any) {
  const selectableRepos = repositories.filter(
    (repo: any) => repo.status !== "failed",
  );

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-white">
      <div className="h-16 border-b border-gray-200 flex items-center px-6 bg-gray-50 flex-shrink-0">
        <label className="text-sm font-medium text-gray-700 mr-3">
          Active Context:
        </label>
        <select
          value={selectedRepoId}
          onChange={(e) => setSelectedRepoId(e.target.value)}
          className="flex-1 max-w-md bg-white border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block p-2 outline-none"
        >
          <option value="" disabled>
            Select a repository...
          </option>
          {selectableRepos.map((repo: any) => (
            <option key={repo.id} value={repo.id}>
              {repoOptionLabel(repo)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-8 bg-gray-50">
        {selectedRepoId ? (
          <DiagramBody key={selectedRepoId} repoId={selectedRepoId} />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <p className="text-lg font-medium text-gray-600">
              Select a repository to see its architecture
            </p>
            <p className="text-sm mt-1">
              Diagrams are generated from the deterministic repository manifest.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
