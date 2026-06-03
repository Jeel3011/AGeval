"use client";

import React, { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [apiKey, setApiKey]   = useState("");
  const [apiUrl, setApiUrl]   = useState("https://ageval-production.up.railway.app");
  const [testing, setTesting] = useState(false);
  const [error, setError]     = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!apiKey.trim()) { setError("API key is required."); return; }

    setTesting(true);
    try {
      const res = await fetch(`${apiUrl}/episodes?limit=1`, {
        headers: { Authorization: `Bearer ${apiKey.trim()}` },
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      localStorage.setItem("ageval_key", apiKey.trim());
      localStorage.setItem("ageval_url", apiUrl.trim());
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Connection failed — check your key and URL.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50 py-12 px-4">
      <div className="max-w-md w-full space-y-8">
        <div className="flex flex-col items-center">
          <div className="w-12 h-12 rounded-xl bg-zinc-900 flex items-center justify-center mb-4">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-3xl font-semibold tracking-tight text-zinc-900">Sign in to AGeval</h2>
          <p className="mt-2 text-sm text-zinc-500">Enter your AGeval API key to connect.</p>
        </div>

        <form onSubmit={handleSubmit} className="mt-8 space-y-5">
          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1">API Key</label>
            <input
              type="password" required autoFocus
              value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="ageval-sk-…"
              className="w-full h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1">API Base URL</label>
            <input
              type="url"
              value={apiUrl} onChange={e => setApiUrl(e.target.value)}
              className="w-full h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900"
            />
            <p className="mt-1 text-xs text-zinc-400">Change to http://localhost:8000 for local development.</p>
          </div>

          {error && (
            <div className="rounded-md bg-rose-50 border border-rose-200 px-4 py-3 text-sm text-rose-700">{error}</div>
          )}

          <button type="submit" disabled={testing}
            className="w-full flex justify-center items-center gap-2 h-10 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-60">
            {testing ? <><Loader2 size={16} className="animate-spin" /> Testing connection…</> : "Connect"}
          </button>
        </form>

        <p className="text-center text-xs text-zinc-400">
          Don&apos;t have a key?{" "}
          <a href="https://github.com/Jeel3011/AGeval#run-the-server" target="_blank" rel="noopener noreferrer"
            className="underline hover:text-zinc-700">
            Set up your server
          </a>{" "}
          and use the <code className="text-xs bg-zinc-100 px-1 rounded">/register</code> endpoint.
        </p>
      </div>
    </div>
  );
}
