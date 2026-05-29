"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Filter, Loader2, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { apiGet, ApiError } from "@/lib/api";

interface Episode {
  episode_id: string;
  agent_id: string;
  task: string | null;
  outcome: string | null;
  total_steps: number | null;
  total_latency_ms: number | null;
  created_at: string;
}

const OUTCOMES = ["", "success", "partial", "failure"] as const;

function fmtAge(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmtLatency(ms: number | null): string {
  if (!ms) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default function TracesPage() {
  const [episodes, setEpisodes]   = useState<Episode[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [search, setSearch]       = useState("");
  const [outcome, setOutcome]     = useState("");
  const [agentId, setAgentId]     = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ limit: "100" });
    if (agentId) params.set("agent_id", agentId);
    apiGet(`/episodes?${params}`)
      .then(d => setEpisodes(d.episodes ?? []))
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setLoading(false));
  }, [agentId]);

  useEffect(() => { load(); }, [load]);

  const filtered = episodes.filter(ep => {
    if (outcome && ep.outcome !== outcome) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        ep.episode_id.includes(q) ||
        (ep.task ?? "").toLowerCase().includes(q) ||
        ep.agent_id.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-6">

        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Traces & Logs</h1>
            <p className="text-zinc-500 mt-1 text-sm">Every agent run — click a row to see the full step timeline.</p>
          </div>
          <button onClick={load} disabled={loading}
            className="flex items-center gap-1.5 h-9 px-3 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:bg-zinc-50 transition-colors shadow-sm disabled:opacity-50">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
        )}

        <div className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden flex flex-col" style={{ height: "72vh" }}>
          {/* Toolbar */}
          <div className="h-14 border-b border-zinc-200 px-4 flex items-center gap-3 bg-zinc-50/50 flex-shrink-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-4 w-4 text-zinc-400" />
              <input
                type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search by ID, task or agent…"
                className="h-8 w-64 rounded-md border border-zinc-200 bg-white pl-9 pr-4 text-sm outline-none focus:border-zinc-300 focus:ring-1 focus:ring-zinc-300"
              />
            </div>

            <select value={outcome} onChange={e => setOutcome(e.target.value)}
              className="h-8 rounded-md border border-zinc-200 bg-white px-2 text-sm text-zinc-700 outline-none focus:border-zinc-300">
              <option value="">All outcomes</option>
              {OUTCOMES.slice(1).map(o => <option key={o} value={o}>{o}</option>)}
            </select>

            <input type="text" value={agentId} onChange={e => setAgentId(e.target.value)}
              placeholder="Filter by agent_id…" onBlur={load}
              className="h-8 w-44 rounded-md border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-300"
            />

            <span className="ml-auto text-xs text-zinc-400">{filtered.length} rows</span>
          </div>

          {/* Table */}
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="flex items-center justify-center h-full text-zinc-400">
                <Loader2 className="animate-spin mr-2" size={20} /> Loading traces…
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex items-center justify-center h-full text-zinc-400 text-sm">
                {episodes.length === 0 ? "No episodes yet — run your first agent." : "No episodes match the current filter."}
              </div>
            ) : (
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 sticky top-0 border-b border-zinc-200">
                  <tr>
                    <th className="px-6 py-3 font-medium">Episode ID</th>
                    <th className="px-6 py-3 font-medium">Task</th>
                    <th className="px-6 py-3 font-medium">Agent</th>
                    <th className="px-6 py-3 font-medium">Steps</th>
                    <th className="px-6 py-3 font-medium">Latency</th>
                    <th className="px-6 py-3 font-medium">Outcome</th>
                    <th className="px-6 py-3 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {filtered.map(ep => (
                    <TraceRow key={ep.episode_id} ep={ep} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

function TraceRow({ ep }: { ep: Episode }) {
  const outcomeColor: Record<string, string> = {
    success: "bg-emerald-100 text-emerald-700",
    failure: "bg-rose-100 text-rose-700",
    partial: "bg-amber-100 text-amber-700",
  };
  const cls = outcomeColor[ep.outcome ?? ""] ?? "bg-zinc-100 text-zinc-500";

  return (
    <tr className="bg-white hover:bg-zinc-50 transition-colors cursor-pointer group">
      <td className="px-6 py-4 font-mono text-xs text-zinc-500 group-hover:text-zinc-900">
        <Link href={`/episodes/${ep.episode_id}`} className="hover:underline">{ep.episode_id}</Link>
      </td>
      <td className="px-6 py-4 font-medium text-zinc-900 max-w-xs truncate">
        {ep.task ?? <span className="text-zinc-400 italic">no task</span>}
      </td>
      <td className="px-6 py-4 font-mono text-xs text-zinc-500">{ep.agent_id}</td>
      <td className="px-6 py-4 text-zinc-600">{ep.total_steps ?? "—"}</td>
      <td className="px-6 py-4 text-zinc-500">{fmtLatency(ep.total_latency_ms)}</td>
      <td className="px-6 py-4">
        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>{ep.outcome ?? "—"}</span>
      </td>
      <td className="px-6 py-4 text-zinc-500 whitespace-nowrap">{fmtAge(ep.created_at)}</td>
    </tr>
  );
}
