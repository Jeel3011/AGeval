'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { TrendingDown, TrendingUp, Minus, RefreshCw, GitCommitHorizontal } from 'lucide-react';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';
import { Reveal } from '@/components/ui/Reveal';

export default function RegressionPage() {
  const { toast } = useToast();
  const [agents, setAgents] = useState<string[]>([]);
  const [agent, setAgent] = useState<string>('');
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiGet('/agents')
      .then((res) => {
        const list = res.agents || [];
        setAgents(list);
        if (list.length) setAgent(list[0]);
      })
      .catch((err: any) => toast(err.message, 'error'));
  }, []);

  useEffect(() => {
    if (agent) run(agent);
  }, [agent]);

  const run = async (a: string) => {
    setLoading(true);
    try {
      const res = await apiGet(`/agents/${encodeURIComponent(a)}/regression`);
      setData(res);
    } catch (err: any) {
      toast(err.message, 'error');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Memory"
        title="Regression Detection"
        lede="Recent runs vs the prior baseline window — surfacing what changed, not just the average."
        actions={
          <div className="flex items-center gap-2">
            <select
              className="h-9 min-w-[200px] rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition"
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
            >
              {agents.length === 0 && <option value="">No agents</option>}
              {agents.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <button
              className="inline-flex items-center gap-2 h-9 px-3.5 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors disabled:opacity-60"
              onClick={() => agent && run(agent)}
              disabled={loading || !agent}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Run
            </button>
          </div>
        }
      />

      {loading ? (
        <div className="ed-card h-72 animate-pulse bg-zinc-50/60" />
      ) : !data ? (
        <EmptyState
          icon={<GitCommitHorizontal size={26} />}
          title="Pick an agent to analyze"
          hint="Select an agent above to compare its recent runs against its prior baseline window."
        />
      ) : (
        <div className="flex flex-col gap-5">
          {/* Verdict banner */}
          <Reveal>
            <div className={`ed-card flex items-center gap-4 p-5 ${data.regressed ? 'border-rose-200' : 'border-emerald-200'}`}>
              {data.regressed ? <TrendingDown size={26} className="text-rose-500" /> : <TrendingUp size={26} className="text-emerald-500" />}
              <div>
                <div className={`text-lg font-semibold ${data.regressed ? 'text-rose-600' : 'text-emerald-600'}`}>
                  {data.regressed ? 'Regression detected' : 'No regression'}
                </div>
                <div className="text-[13px] text-zinc-400">
                  {data.window?.after_n} recent runs vs {data.window?.baseline_n} baseline runs
                </div>
              </div>
            </div>
          </Reveal>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Reveal delay={60} variant="left">
              <div className="ed-card p-6 h-full">
                <h3 className="text-sm font-semibold text-zinc-700 mb-4">Score deltas</h3>
                {Object.keys(data.score_deltas || {}).length === 0 ? (
                  <div className="text-[13px] text-zinc-400">No overlapping scores between windows.</div>
                ) : (
                  <div className="flex flex-col gap-3.5">
                    {Object.entries(data.score_deltas).map(([scorer, d]: [string, any]) => (
                      <DeltaRow key={scorer} label={scorer} d={d} />
                    ))}
                  </div>
                )}
              </div>
            </Reveal>

            <Reveal delay={120}>
              <div className="ed-card p-6 h-full">
                <h3 className="text-sm font-semibold text-zinc-700 mb-4">Drift</h3>
                <div className="flex flex-col gap-3.5">
                  <DriftRow label="Avg steps" a={data.step_drift?.baseline} b={data.step_drift?.after} inverse />
                  <DriftRow label="Success rate" a={data.outcome_shift?.baseline?.success} b={data.outcome_shift?.after?.success} pct />
                  <DriftRow label="Failure rate" a={data.outcome_shift?.baseline?.failure} b={data.outcome_shift?.after?.failure} pct inverse />
                </div>
              </div>
            </Reveal>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Reveal delay={60} variant="left">
              <div className="ed-card p-6 h-full">
                <h3 className="text-sm font-semibold text-zinc-700 mb-3">New failure signatures</h3>
                {(data.new_failures || []).length === 0 ? (
                  <div className="text-[13px] text-zinc-400">None — no new failure modes appeared.</div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {data.new_failures.map((f: string) => (
                      <div key={f} className="font-mono text-xs px-3 py-2 rounded-lg border border-rose-100 bg-rose-50 text-rose-600">{f}</div>
                    ))}
                  </div>
                )}
              </div>
            </Reveal>
            <Reveal delay={120}>
              <div className="ed-card p-6 h-full">
                <h3 className="text-sm font-semibold text-zinc-700 mb-3">New trajectory shapes</h3>
                {(data.new_trajectories || []).length === 0 ? (
                  <div className="text-[13px] text-zinc-400">None — the agent took familiar paths.</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {data.new_trajectories.map((t: string) => (
                      <span key={t} className="badge badge-warning font-mono">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            </Reveal>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function DeltaRow({ label, d }: { label: string; d: any }) {
  const delta = d.delta;
  const up = delta != null && delta > 0.001;
  const down = delta != null && delta < -0.001;
  const color = down ? 'var(--danger)' : up ? 'var(--success)' : 'var(--text-muted)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ textTransform: 'capitalize' }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <span style={{ color: 'var(--text-muted)' }}>{fmt(d.a)} → {fmt(d.b)}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontWeight: 600, color }}>
          {down ? <TrendingDown size={14} /> : up ? <TrendingUp size={14} /> : <Minus size={14} />}
          {delta == null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}`}
        </span>
      </div>
    </div>
  );
}

function DriftRow({ label, a, b, pct, inverse }: { label: string; a: number | null; b: number | null; pct?: boolean; inverse?: boolean }) {
  const diff = a != null && b != null ? b - a : null;
  // For "inverse" rows (steps, failure rate) an increase is bad.
  const bad = diff != null && (inverse ? diff > 0.001 : diff < -0.001);
  const good = diff != null && (inverse ? diff < -0.001 : diff > 0.001);
  const color = bad ? 'var(--danger)' : good ? 'var(--success)' : 'var(--text-muted)';
  const show = (v: number | null) => v == null ? '—' : pct ? `${Math.round(v * 100)}%` : v.toFixed(1);
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span>{label}</span>
      <span style={{ fontSize: 13, color }}>{show(a)} → {show(b)}</span>
    </div>
  );
}

function fmt(v: number | null) { return v == null ? '—' : v.toFixed(2); }
