import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";
import api from "../api/axiosConfig";

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  theme: "default",
});

// Mermaid.render needs a DOM id that is unique at call time. React StrictMode
// runs effects twice in development, so a module counter is safer than useId.
let renderCounter = 0;

function Mermaid({ chart }: { chart: string }) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const reactId = useId();

  useEffect(() => {
    let active = true;
    const id = `mermaid-${reactId.replace(/[^a-zA-Z0-9]/g, "")}-${renderCounter++}`;

    mermaid
      .render(id, chart)
      .then((result) => {
        if (active) setSvg(result.svg);
      })
      .catch((err: any) => {
        if (active) setError(err?.message || "Could not render this diagram.");
      });

    return () => {
      active = false;
    };
  }, [chart, reactId]);

  if (error) {
    return (
      <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3">
        {error}
      </p>
    );
  }

  return (
    <div
      className="overflow-x-auto bg-white border border-gray-200 rounded-lg p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

const SECTIONS: { key: string; title: string }[] = [
  { key: "languages", title: "Language mix" },
  { key: "directories", title: "Directory map" },
  { key: "entrypoints", title: "Entrypoints" },
];

// Keyed by repo id from the parent, so switching repositories remounts this and
// resets its state without a setState call inside an effect body.
function DiagramBody({ repoId }: { repoId: string }) {
  const [diagrams, setDiagrams] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    api
      .get(`/repos/${repoId}/diagrams`)
      .then((res) => {
        if (!cancelled) setDiagrams(res.data.diagrams);
      })
      .catch((err: any) => {
        if (cancelled) return;
        setError(
          err.response?.data?.detail || err.message || "Failed to load diagrams.",
        );
      });

    return () => {
      cancelled = true;
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
      {SECTIONS.map((section) => (
        <section key={section.key}>
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-3">
            {section.title}
          </h2>
          <Mermaid chart={diagrams[section.key] ?? ""} />
        </section>
      ))}
    </>
  );
}

export default function ArchitectureView({
  repositories,
  selectedRepoId,
  setSelectedRepoId,
}: any) {
  const readyRepos = repositories.filter(
    (repo: any) => repo.status === "completed",
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
          {readyRepos.map((repo: any) => (
            <option key={repo.id} value={repo.id}>
              {repo.full_name}
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
