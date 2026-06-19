'use client';

import { useEffect, useState } from 'react';
import { apiGet, apiPostStream } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { Gauge, RefreshCw, ChevronRight, ShieldCheck, ShieldAlert, AlertTriangle, Ban, Info, Play, Radio } from 'lucide-react';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';
import { Reveal } from '@/components/ui/Reveal';

// ---- types mirror the backend payloads ------------------------------------
interface EpisodeRow {
  episode_id: string;
  agent_id: string;
  task: string | null;
  total_steps?: number;
  created_at?: string;
}
interface Driver { metric: string; value: number; shortfall: number; }
interface Provenance { scorer: string; score: number | null; top_drivers: Driver[]; all_metrics: Driver[]; }
interface Verdict { step_index: number; action: string; score: number; confidence: number; reasons: { layer?: string; message?: string }[]; matched_signature?: string | null; }
interface Failure { step_index: number; tool: string; error_category: string | null; recoverable: boolean | null; }
interface Explain {
  episode_id: string;
  agent_id: string;
  task: string | null;
  summary: string;
  score_provenance: Provenance[];
  tools_used: string[];
  failures: Failure[];
  live_verdict_trail: Verdict[];
  step_count: number;
}

const ACTION_META: Record<string, { icon: any; cls: string; label: string }> = {
  allow:    { icon: ShieldCheck,   cls: 'text-emerald-600 bg-emerald-50 border-emerald-200', label: 'allow' },
  warn:     { icon: AlertTriangle, cls: 'text-amber-600 bg-amber-50 border-amber-200',       label: 'warn' },
  escalate: { icon: ShieldAlert,   cls: 'text-orange-600 bg-orange-50 border-orange-200',    label: 'escalate' },
  block:    { icon: Ban,           cls: 'text-red-600 bg-red-50 border-red-200',             label: 'block' },
};

function ActionPill({ action }: { action: string }) {
  const m = ACTION_META[action] || ACTION_META.allow;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${m.cls}`}>
      <Icon size={12} /> {m.label}
    </span>
  );
}

export default function LiveEvalPage() {
  const { toast } = useToast();
  const [tab, setTab] = useState<'recorded' | 'live'>('recorded');
  const [episodes, setEpisodes] = useState<EpisodeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [explain, setExplain] = useState<Explain | null>(null);
  const [explaining, setExplaining] = useState(false);

  useEffect(() => { loadEpisodes(); }, []);

  const loadEpisodes = async () => {
    setLoading(true);
    try {
      const res = await apiGet('/episodes?limit=50');
      const rows: EpisodeRow[] = Array.isArray(res) ? res : (res.episodes || []);
      setEpisodes(rows);
      // Deep-link support: /live-eval?ep=<id> opens that episode directly.
      const deep = typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search).get('ep') : null;
      const target = deep && rows.some((r) => r.episode_id === deep) ? deep : (rows[0]?.episode_id);
      if (target && !selected) openEpisode(target);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const openEpisode = async (id: string) => {
    setSelected(id);
    setExplaining(true);
    setExplain(null);
    try {
      const res = await apiGet(`/episodes/${encodeURIComponent(id)}/explain`);
      setExplain(res);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setExplaining(false);
    }
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Guardrails"
        title="Live Eval"
        lede="Watch the evaluator think. Every step is scored against this agent's memory as it runs — see the live verdict trail, then the provenance behind the final score."
        actions={
          tab === 'recorded' ? (
            <button
              onClick={loadEpisodes}
              disabled={loading}
              className="inline-flex items-center gap-2 h-9 px-3.5 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors disabled:opacity-60"
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          ) : null
        }
      />

      {/* tab bar */}
      <div className="flex items-center gap-1 mb-6 -mt-2">
        <button
          onClick={() => setTab('recorded')}
          className={`inline-flex items-center gap-2 h-9 px-3.5 rounded-lg text-sm font-medium transition-colors ${tab === 'recorded' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100'}`}
        >
          <Gauge size={15} /> Recorded
        </button>
        <button
          onClick={() => setTab('live')}
          className={`inline-flex items-center gap-2 h-9 px-3.5 rounded-lg text-sm font-medium transition-colors ${tab === 'live' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100'}`}
        >
          <Radio size={15} /> Run live
        </button>
      </div>

      {tab === 'live' ? (
        <RunLive episodes={episodes} />
      ) : loading ? (
        <div className="text-sm text-zinc-400">Loading episodes…</div>
      ) : !episodes.length ? (
        <EmptyState
          icon={<Gauge size={26} />}
          title="No episodes yet"
          hint="Run an agent or workflow that records to AGeval (e.g. python -m examples.agents.fleet.workflows.run_workflows --explain), then refresh."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
          {/* ---- episode list ---- */}
          <div className="flex flex-col gap-1.5">
            {episodes.map((e) => (
              <button
                key={e.episode_id}
                onClick={() => openEpisode(e.episode_id)}
                className={`text-left ed-card px-4 py-3 transition-colors ${selected === e.episode_id ? 'ring-2 ring-zinc-900' : 'hover:bg-zinc-50'}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-zinc-800 truncate">{e.agent_id}</span>
                  <ChevronRight size={14} className="text-zinc-300 shrink-0" />
                </div>
                <div className="text-xs text-zinc-500 truncate mt-0.5">{e.task || 'No task'}</div>
                <div className="text-[11px] text-zinc-400 mt-1 font-mono">{e.episode_id}</div>
              </button>
            ))}
          </div>

          {/* ---- detail ---- */}
          <div>
            {explaining ? (
              <div className="text-sm text-zinc-400">Reading provenance…</div>
            ) : !explain ? (
              <EmptyState icon={<Info size={24} />} title="Select an episode" hint="Pick a run on the left to see its verdict trail and score provenance." />
            ) : (
              <Reveal>
                {/* summary */}
                <div className="ed-card px-5 py-4 mb-5">
                  <div className="ed-kicker mb-1">{explain.agent_id}</div>
                  <div className="text-[15px] text-zinc-800 leading-relaxed">{explain.task}</div>
                  <p className="mt-3 text-sm text-zinc-600 leading-relaxed">{explain.summary}</p>
                  {explain.tools_used?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {explain.tools_used.map((t, i) => (
                        <span key={i} className="rounded-md bg-zinc-100 px-2 py-0.5 text-[11px] font-mono text-zinc-600">{t}</span>
                      ))}
                    </div>
                  )}
                </div>

                {/* live verdict trail */}
                <div className="ed-card px-5 py-4 mb-5">
                  <h3 className="text-sm font-semibold text-zinc-800 mb-1 flex items-center gap-2">
                    <Gauge size={16} /> Live verdict trail
                  </h3>
                  <p className="text-xs text-zinc-400 mb-3">The verdict rendered before each step ran — the transparency stream.</p>
                  {!explain.live_verdict_trail?.length ? (
                    <p className="text-sm text-zinc-400">No live verdicts recorded for this run (the agent didn't call evaluate_step, or the run predates live eval).</p>
                  ) : (
                    <ol className="flex flex-col gap-2">
                      {explain.live_verdict_trail.map((v, i) => (
                        <li key={i} className="flex items-start gap-3 border-l-2 border-zinc-100 pl-3 py-1">
                          <span className="text-[11px] font-mono text-zinc-400 mt-0.5 w-6 shrink-0">#{v.step_index}</span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <ActionPill action={v.action} />
                              <span className="text-xs text-zinc-400">conf {(v.confidence ?? 0).toFixed(2)}</span>
                            </div>
                            {v.reasons?.length > 0 && (
                              <div className="mt-1 text-xs text-zinc-600">
                                {v.reasons.map((r, j) => (
                                  <span key={j}>{r.layer ? <b className="text-zinc-700">{r.layer}: </b> : null}{r.message}{j < v.reasons.length - 1 ? ' · ' : ''}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>

                {/* score provenance */}
                <div className="ed-card px-5 py-4 mb-5">
                  <h3 className="text-sm font-semibold text-zinc-800 mb-1">Why this score</h3>
                  <p className="text-xs text-zinc-400 mb-3">Each scorer's metrics, ranked by how far they fell short of a perfect 1.0.</p>
                  {!explain.score_provenance?.length ? (
                    <p className="text-sm text-zinc-400">Not scored yet — the merge/scoring worker may still be running.</p>
                  ) : (
                    <div className="flex flex-col gap-4">
                      {explain.score_provenance.map((p, i) => (
                        <div key={i}>
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-[13px] font-medium text-zinc-700">{p.scorer}</span>
                            <span className="text-[13px] font-mono text-zinc-900">{p.score != null ? p.score.toFixed(3) : '—'}</span>
                          </div>
                          <div className="flex flex-col gap-1.5">
                            {p.top_drivers.map((d, j) => (
                              <div key={j} className="flex items-center gap-2">
                                <span className="text-xs text-zinc-500 w-44 truncate">{d.metric}</span>
                                <div className="flex-1 h-2 rounded-full bg-zinc-100 overflow-hidden">
                                  <div
                                    className={`h-full ${d.shortfall > 0 ? 'bg-zinc-800' : 'bg-emerald-400'}`}
                                    style={{ width: `${Math.round((d.value ?? 0) * 100)}%` }}
                                  />
                                </div>
                                <span className="text-[11px] font-mono text-zinc-500 w-10 text-right">{(d.value ?? 0).toFixed(2)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* failures */}
                {explain.failures?.length > 0 && (
                  <div className="ed-card px-5 py-4">
                    <h3 className="text-sm font-semibold text-zinc-800 mb-3 flex items-center gap-2">
                      <ShieldAlert size={16} /> Failed steps
                    </h3>
                    <ul className="flex flex-col gap-1.5">
                      {explain.failures.map((f, i) => (
                        <li key={i} className="text-sm text-zinc-600 flex items-center gap-2">
                          <span className="text-[11px] font-mono text-zinc-400">#{f.step_index}</span>
                          <span className="font-mono text-zinc-700">{f.tool}</span>
                          {f.error_category && <span className="rounded bg-red-50 text-red-600 border border-red-200 px-1.5 py-0.5 text-[11px]">{f.error_category}</span>}
                          {f.recoverable != null && <span className="text-xs text-zinc-400">{f.recoverable ? 'recoverable' : 'non-recoverable'}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Reveal>
            )}
          </div>
        </div>
      )}
    </PageContainer>
  );
}

// ---------------------------------------------------------------------------
// Run live: stream a verdict per step as a proposed run is evaluated against
// the agent's real memory. The step sequence is pulled from a recorded episode
// of that agent (its actual trajectory); toggle "deviate" to scramble the order
// and watch the golden-path layer object.
// ---------------------------------------------------------------------------
interface StreamVerdict {
  event: string; step_index: number; tool_name: string; action: string;
  score: number; confidence: number; reasons: { layer?: string; message?: string }[];
  latency_ms?: number;
}

function RunLive({ episodes }: { episodes: EpisodeRow[] }) {
  const { toast } = useToast();
  const agents = Array.from(new Set(episodes.map((e) => e.agent_id)));
  const [agent, setAgent] = useState<string>(agents[0] || '');
  const [deviate, setDeviate] = useState(false);
  const [running, setRunning] = useState(false);
  const [memory, setMemory] = useState<{ signatures: number; has_golden: boolean; numeric_baselines: number } | null>(null);
  const [verdicts, setVerdicts] = useState<StreamVerdict[]>([]);

  const run = async () => {
    if (!agent) { toast('Pick an agent first', 'error'); return; }
    setRunning(true); setVerdicts([]); setMemory(null);
    try {
      // Pull a recorded episode of this agent to get its real step sequence.
      const ep = episodes.find((e) => e.agent_id === agent);
      let steps: { tool_name: string; reasoning?: string }[] = [];
      if (ep) {
        const detail = await apiGet(`/episodes/${encodeURIComponent(ep.episode_id)}/steps`);
        steps = (detail.steps || [])
          .filter((s: any) => s.tool_name && s.tool_name !== 'llm_call')
          .map((s: any) => ({ tool_name: s.tool_name, reasoning: s.reasoning }));
      }
      if (!steps.length) steps = [{ tool_name: 'http_get' }, { tool_name: 'calculate' }];
      if (deviate) steps = [...steps].reverse();  // scramble to provoke the golden-path layer

      await apiPostStream('/evaluate/stream', { agent_id: agent, steps }, (data) => {
        if (data.event === 'start') setMemory(data.memory);
        else if (data.event === 'verdict') setVerdicts((prev) => [...prev, data]);
      });
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setRunning(false);
    }
  };

  const hasTeeth = memory && (memory.signatures > 0 || memory.has_golden || memory.numeric_baselines > 0);

  return (
    <div>
      <div className="ed-card px-5 py-4 mb-5 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Agent</label>
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="h-9 px-3 rounded-lg border border-zinc-200 bg-white text-sm text-zinc-800 min-w-[260px]"
          >
            {agents.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-600 h-9">
          <input type="checkbox" checked={deviate} onChange={(e) => setDeviate(e.target.checked)} />
          Deviate from golden path
        </label>
        <button
          onClick={run}
          disabled={running || !agent}
          className="inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-60 ml-auto"
        >
          <Play size={15} /> {running ? 'Streaming…' : 'Run live'}
        </button>
      </div>

      {memory && (
        <div className="ed-card px-5 py-3 mb-5 text-sm flex items-center gap-4 flex-wrap">
          <span className="text-zinc-500">Memory behind this agent:</span>
          <span className="text-zinc-700">{memory.signatures} failure signature(s)</span>
          <span className="text-zinc-700">{memory.has_golden ? 'golden path ✓' : 'no golden path'}</span>
          <span className="text-zinc-700">{memory.numeric_baselines} input baseline(s)</span>
          {!hasTeeth && <span className="text-amber-600">cold start — verdicts will be advisory allow until memory fills</span>}
        </div>
      )}

      {!verdicts.length && !running ? (
        <EmptyState icon={<Radio size={24} />} title="Run a live evaluation"
          hint="Pick an agent and press Run live. Each step's verdict streams in as the engine scores the proposed trajectory against the agent's memory." />
      ) : (
        <div className="ed-card px-5 py-4">
          <h3 className="text-sm font-semibold text-zinc-800 mb-3 flex items-center gap-2">
            <Radio size={16} className={running ? 'animate-pulse text-emerald-500' : ''} /> Verdict stream
          </h3>
          <ol className="flex flex-col gap-2">
            {verdicts.map((v, i) => (
              <li key={i} className="flex items-start gap-3 border-l-2 border-zinc-100 pl-3 py-1 ag-step-in">
                <span className="text-[11px] font-mono text-zinc-400 mt-0.5 w-6 shrink-0">#{v.step_index}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[13px] text-zinc-700">{v.tool_name}</span>
                    <ActionPill action={v.action} />
                    <span className="text-xs text-zinc-400">conf {(v.confidence ?? 0).toFixed(2)}</span>
                    {v.latency_ms != null && <span className="text-[11px] text-zinc-300">{v.latency_ms}ms</span>}
                  </div>
                  {v.reasons?.length > 0 && (
                    <div className="mt-1 text-xs text-zinc-600">
                      {v.reasons.map((r, j) => (
                        <span key={j}>{r.layer ? <b className="text-zinc-700">{r.layer}: </b> : null}{r.message}{j < v.reasons.length - 1 ? ' · ' : ''}</span>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            ))}
            {running && <li className="text-xs text-zinc-400 pl-9">scoring…</li>}
          </ol>
        </div>
      )}
    </div>
  );
}
