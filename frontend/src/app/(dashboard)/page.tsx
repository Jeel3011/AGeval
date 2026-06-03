"use client";

import React, { useEffect, useState } from "react";
import { ChevronRight, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { apiGet, ApiError } from "@/lib/api";

interface Episode {
  episode_id: string;
  agent_id: string;
  task: string | null;
  outcome: string | null;
  total_steps: number | null;
  created_at: string;
}

interface Overview {
  total_episodes: number;
  success_rate: number;
  failure_rate: number;
  partial_rate: number;
  avg_steps: number;
  avg_latency_ms: number;
  agent_count: number;
  scores: Record<string, number>;
  metric_breakdown: Record<string, number>;
}

export default function DashboardOverview() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiGet("/overview"),
      apiGet("/episodes?limit=50"),
    ])
      .then(([ov, eps]) => {
        setOverview(ov);
        setEpisodes(eps.episodes ?? []);
      })
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const failures = episodes.filter(e => e.outcome === "failure").slice(0, 5);
  const pct = (v: number | undefined) => Math.round((v ?? 0) * 100);
  const avgScore = overview?.scores?.custom ?? overview?.scores?.rules;

  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-8">

        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Overview</h1>
            <p className="text-zinc-500 mt-1 text-sm">Live agent performance from your last 50 episodes.</p>
          </div>
          <div className="flex gap-2">
            <button onClick={load} disabled={loading}
              className="flex items-center gap-1.5 h-9 px-3 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:bg-zinc-50 transition-colors shadow-sm disabled:opacity-50">
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <Link href="/episodes"
              className="h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm flex items-center">
              View Episodes
            </Link>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error === "No API key set. Click Settings to connect."
              ? <span>No API key set. Go to <Link href="/settings" className="underline font-medium">Settings → Generate Key</Link> to connect.</span>
              : error}
          </div>
        )}

        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm animate-pulse h-24" />
            ))
          ) : (
            <>
              <KpiCard title="Total Episodes"  value={(overview?.total_episodes ?? 0).toLocaleString()} sub={`${overview?.agent_count ?? 0} agents tracked`} />
              <KpiCard title="Success Rate"    value={`${pct(overview?.success_rate)}%`} sub="episodes with outcome=success" positive />
              <KpiCard
                title="Avg Score"
                value={avgScore !== undefined ? avgScore.toFixed(2) : "—"}
                sub={overview?.scores?.custom !== undefined ? "custom-metric composite" : overview?.scores?.rules !== undefined ? "rule-based composite" : "no scores yet"}
                positive={avgScore !== undefined && avgScore >= 0.7}
                negative={avgScore !== undefined && avgScore < 0.5}
              />
              <KpiCard title="Avg Steps" value={String(Math.round(overview?.avg_steps ?? 0))} sub="tool calls per episode" />
            </>
          )}
        </div>

        {/* Metric breakdown — averaged across episodes, from the custom scorer */}
        {!loading && overview && Object.keys(overview.metric_breakdown ?? {}).length > 0 && (
          <div className="border border-zinc-200 bg-white rounded-xl shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-zinc-900">Metric Breakdown</h3>
              <span className="text-xs text-zinc-400">averaged across last {overview.total_episodes} episodes</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              {Object.entries(overview.metric_breakdown)
                .sort((a, b) => a[1] - b[1])
                .map(([name, val]) => (
                  <MetricRow key={name} name={name} value={val} />
                ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-3 gap-6">
          {/* Recent episodes mini-table */}
          <div className="col-span-2 border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
              <h3 className="font-semibold text-zinc-900">Recent Episodes</h3>
              <Link href="/episodes" className="text-xs text-zinc-500 hover:text-zinc-900 transition-colors">View all →</Link>
            </div>
            {loading ? (
              <div className="flex items-center justify-center h-48 text-zinc-400">
                <Loader2 className="animate-spin" size={20} />
              </div>
            ) : episodes.length === 0 ? (
              <div className="flex items-center justify-center h-48 text-zinc-400 text-sm">
                No episodes yet — run your first agent with the SDK.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 border-b border-zinc-100">
                  <tr>
                    <th className="px-6 py-2 text-left font-medium">Task</th>
                    <th className="px-6 py-2 text-left font-medium">Steps</th>
                    <th className="px-6 py-2 text-left font-medium">Outcome</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {episodes.slice(0, 8).map(ep => (
                    <tr key={ep.episode_id} className="hover:bg-zinc-50 transition-colors cursor-pointer">
                      <td className="px-6 py-3 font-medium text-zinc-900 truncate max-w-xs">
                        <Link href={`/episodes/${ep.episode_id}`} className="hover:underline">
                          {ep.task ?? ep.agent_id}
                        </Link>
                      </td>
                      <td className="px-6 py-3 text-zinc-500">{ep.total_steps ?? "—"}</td>
                      <td className="px-6 py-3">
                        <OutcomeBadge outcome={ep.outcome} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Recent failures */}
          <div className="col-span-1 border border-zinc-200 bg-white rounded-xl shadow-sm p-6 flex flex-col">
            <h3 className="font-semibold text-zinc-900 mb-4">Recent Failures</h3>
            {loading ? (
              <div className="flex-1 flex items-center justify-center text-zinc-400">
                <Loader2 className="animate-spin" size={18} />
              </div>
            ) : failures.length === 0 ? (
              <div className="flex-1 flex items-center justify-center text-zinc-400 text-sm text-center">
                No failures in the last 50 episodes 🎉
              </div>
            ) : (
              <div className="flex-1 flex flex-col gap-3">
                {failures.map(ep => (
                  <Link key={ep.episode_id} href={`/episodes/${ep.episode_id}`}>
                    <div className="flex items-center justify-between p-3 rounded-lg border border-zinc-100 bg-zinc-50/50 hover:bg-zinc-50 transition-colors cursor-pointer">
                      <div className="flex flex-col gap-0.5 truncate pr-4">
                        <span className="text-sm font-medium text-zinc-900 truncate">{ep.task ?? ep.agent_id}</span>
                        <span className="text-xs text-zinc-500">{ep.total_steps ?? 0} steps</span>
                      </div>
                      <ChevronRight size={14} className="text-zinc-400 shrink-0" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
            <Link href="/episodes?outcome=failure"
              className="mt-4 w-full py-2 text-sm text-zinc-600 font-medium hover:text-zinc-900 hover:bg-zinc-50 rounded-md transition-colors text-center">
              View all failures →
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}

function KpiCard({ title, value, sub, positive, negative }: {
  title: string; value: string; sub: string; positive?: boolean; negative?: boolean;
}) {
  return (
    <div className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm flex flex-col gap-2">
      <div className="text-sm font-medium text-zinc-500">{title}</div>
      <div className="text-2xl font-semibold text-zinc-900 tracking-tight">{value}</div>
      <div className={`text-xs font-medium ${positive ? "text-emerald-600" : negative ? "text-rose-600" : "text-zinc-400"}`}>
        {sub}
      </div>
    </div>
  );
}

function MetricRow({ name, value }: { name: string; value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-emerald-500" : value >= 0.5 ? "bg-amber-500" : "bg-rose-500";
  const label = name.replace(/_/g, " ");
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-zinc-600 w-44 shrink-0 capitalize truncate" title={label}>{label}</span>
      <div className="flex-1 bg-zinc-100 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all duration-700`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-medium text-zinc-700 w-10 text-right tabular-nums">{value.toFixed(2)}</span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const map: Record<string, string> = {
    success: "bg-emerald-100 text-emerald-700",
    failure: "bg-rose-100 text-rose-700",
    partial: "bg-amber-100 text-amber-700",
  };
  const cls = map[outcome ?? ""] ?? "bg-zinc-100 text-zinc-500";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>
      {outcome ?? "unknown"}
    </span>
  );
}
