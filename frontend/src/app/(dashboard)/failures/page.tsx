'use client';
import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { ShieldAlert, RefreshCw, FlaskConical, ChevronRight, X } from 'lucide-react';
import Link from 'next/link';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';
import { Reveal } from '@/components/ui/Reveal';

interface Signature {
  id: string;
  agent_id: string;
  signature: string;
  label: string | null;
  occurrences: number;
  first_seen: string | null;
  last_seen: string | null;
  sample_episode_id: string | null;
  sample_error: string | null;
}

export default function FailuresPage() {
  const { toast } = useToast();
  const [sigs, setSigs] = useState<Signature[]>([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<any>(null);
  const [generating, setGenerating] = useState<string | null>(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiGet('/v1/failures');
      setSigs(Array.isArray(res) ? res : []);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (s: Signature) => {
    try {
      const res = await apiGet(`/v1/failures/${s.id}`);
      setDetail(res);
    } catch (err: any) {
      toast(err.message, 'error');
    }
  };

  const generateEval = async (s: Signature) => {
    setGenerating(s.id);
    try {
      // project_id defaults to the agent_id so the regression dataset is scoped sensibly.
      const res = await apiPost(`/v1/failures/${s.id}/generate-eval`, { project_id: s.agent_id });
      toast(`Created regression dataset “${res.name}”`, 'success');
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setGenerating(null);
    }
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Memory"
        title="Failure Memory"
        lede="How your agents fail — recurring signatures mined from production runs, each one turnable into a regression test."
        actions={
          <button
            className="inline-flex items-center gap-2 h-9 px-3.5 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors disabled:opacity-60"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        }
      />

      {loading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="ed-card h-[92px] animate-pulse bg-zinc-50/60" />
          ))}
        </div>
      ) : sigs.length === 0 ? (
        <EmptyState
          icon={<ShieldAlert size={26} />}
          title="No failure signatures yet"
          hint="They appear automatically once your agents record failing steps. Run an agent that hits an error to see it triaged here."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {sigs.map((s, idx) => (
            <Reveal key={s.id} delay={idx * 50}>
              <div className="ed-card flex items-center gap-5 p-5">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1.5">
                    <span className="font-semibold text-[15px] text-zinc-900 truncate">{s.label || s.signature}</span>
                    <span className="shrink-0 inline-flex items-center rounded-full bg-rose-50 text-rose-600 border border-rose-100 px-2 py-0.5 text-[11px] font-semibold tabular-nums">
                      {s.occurrences} {s.occurrences === 1 ? 'run' : 'runs'}
                    </span>
                  </div>
                  <div className="font-mono text-xs text-zinc-400 truncate">{s.signature}</div>
                  {s.sample_error && (
                    <div className="text-xs text-zinc-500 mt-2 italic truncate">
                      “{s.sample_error.slice(0, 140)}{s.sample_error.length > 140 ? '…' : ''}”
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    className="inline-flex items-center gap-2 h-9 px-3.5 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors whitespace-nowrap disabled:opacity-60"
                    onClick={() => generateEval(s)}
                    disabled={generating === s.id}
                    title="Turn this failure into a golden-dataset regression test"
                  >
                    <FlaskConical size={14} /> {generating === s.id ? 'Creating…' : 'Generate test'}
                  </button>
                  <button
                    className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900 transition-colors"
                    onClick={() => openDetail(s)}
                    aria-label="View occurrences"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      )}

      {detail && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/50 backdrop-blur-sm p-4 animate-in fade-in duration-200"
          onClick={() => setDetail(null)}
        >
          <div
            className="ed-card w-[640px] max-w-[92vw] max-h-[82vh] overflow-y-auto p-6 shadow-2xl animate-in zoom-in-95 fade-in duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="ed-kicker mb-1">Failure signature</div>
                <h2 className="text-lg font-semibold text-zinc-900">{detail.failure?.label || detail.failure?.signature}</h2>
              </div>
              <button
                className="inline-flex items-center justify-center h-8 w-8 rounded-lg border border-zinc-200 text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50 transition-colors"
                onClick={() => setDetail(null)}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
            <div className="font-mono text-xs text-zinc-500 mb-3 break-all">{detail.failure?.signature}</div>
            <div className="text-[13px] text-zinc-400 mb-6">
              Seen {detail.failure?.occurrences} times · first {detail.failure?.first_seen?.slice(0, 10)} · last {detail.failure?.last_seen?.slice(0, 10)}
            </div>
            <h3 className="text-sm font-semibold text-zinc-700 mb-3">Occurrences ({detail.occurrences?.length ?? 0})</h3>
            <div className="flex flex-col gap-2">
              {(detail.occurrences || []).map((o: any, i: number) => (
                <Link
                  key={i}
                  href={`/episodes/${o.episode_id}`}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50 transition-colors"
                >
                  <span className="font-mono text-xs text-zinc-700">{o.episode_id}</span>
                  <span className="text-xs text-zinc-400">step {o.step_index ?? '—'} · {o.occurred_at?.slice(0, 10)}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
