export default function AuthView({
  email,
  setEmail,
  password,
  setPassword,
  handleLogin,
  handleRegister,
  message,
}: any) {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="w-full max-w-md p-8 space-y-6 bg-white rounded-xl shadow-lg border border-gray-100">
        <div className="text-center">
          <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">
            RepoMind AI
          </h1>
          <p className="mt-2 text-sm text-gray-500">
            Sign in to your workspace
          </p>
        </div>
        {message && (
          <div className="p-3 text-sm text-blue-700 bg-blue-50 rounded-lg">
            {message}
          </div>
        )}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2 mt-1 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
              placeholder="developer@example.com"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2 mt-1 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
              placeholder="••••••••"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleLogin}
              className="w-full px-4 py-2 text-white bg-blue-600 rounded-lg hover:bg-blue-700 font-medium transition-colors"
            >
              Login
            </button>
            <button
              onClick={handleRegister}
              className="w-full px-4 py-2 text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 font-medium transition-colors"
            >
              Register
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
