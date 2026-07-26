export default function Sidebar({
  userProfile,
  repositories,
  repoUrl,
  setRepoUrl,
  handleAddRepo,
  handleReprocessRepo,
  handleDeleteRepo,
  handleLogout,
}: any) {
  return (
    <div className="w-80 flex flex-col h-screen bg-gray-900 text-white border-r border-gray-800 flex-shrink-0">
      <div className="p-6 border-b border-gray-800">
        <h2 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400">
          RepoMind AI
        </h2>
        <p className="text-xs text-gray-400 mt-1 truncate">
          {userProfile?.email}
        </p>
      </div>

      <div className="p-4 border-b border-gray-800 bg-gray-800/50">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Import Repository
        </h3>
        <div className="flex flex-col gap-2">
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/..."
            className="w-full px-3 py-2 text-sm bg-gray-900 border border-gray-700 rounded-md focus:ring-1 focus:ring-blue-500 outline-none text-gray-200"
          />
          <button
            onClick={handleAddRepo}
            className="w-full px-3 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
          >
            Add to Workspace
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Your Repositories
        </h3>
        {repositories.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No repositories imported yet.
          </p>
        ) : (
          <ul className="space-y-3">
            {repositories.map((repo: any) => (
              <li
                key={repo.id}
                className="bg-gray-800 rounded-lg p-3 border border-gray-700"
              >
                <div
                  className="font-medium text-sm truncate"
                  title={repo.full_name}
                >
                  {repo.name}
                </div>

                <div className="mt-2 flex items-center justify-between">
                  {repo.status === "completed" && repo.has_embeddings ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-900 text-green-300">
                      Ready
                    </span>
                  ) : repo.status === "completed" && !repo.has_embeddings ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-900 text-red-300">
                      Needs Re-import
                    </span>
                  ) : repo.status === "failed" ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-900 text-red-300">
                      Failed
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-900 text-yellow-300 animate-pulse">
                      Processing...
                    </span>
                  )}

                  <div className="flex gap-2">
                    {(!repo.has_embeddings || repo.status === "failed") && (
                      <button
                        onClick={() => handleReprocessRepo(repo.id)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                        title="Re-import"
                      >
                        ↻
                      </button>
                    )}
                    <button
                      onClick={() => handleDeleteRepo(repo.id)}
                      className="text-xs text-red-400 hover:text-red-300"
                      title="Delete"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="p-4 border-t border-gray-800">
        <button
          onClick={handleLogout}
          className="w-full px-3 py-2 text-sm text-gray-400 bg-gray-800 rounded-md hover:bg-gray-700 transition-colors"
        >
          Log Out
        </button>
      </div>
    </div>
  );
}
