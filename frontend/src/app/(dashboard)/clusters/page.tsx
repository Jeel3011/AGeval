'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor } from '@/lib/utils';
import Link from 'next/link';
import { Network, X } from 'lucide-react';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';
import { Reveal } from '@/components/ui/Reveal';

export default function ClustersPage() {
  const { toast } = useToast();
  const [clusters, setClusters] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadClusters();
  }, []);

  const loadClusters = async () => {
    try {
      // Assuming GET /clusters exists
      const res = await apiGet('/clusters');
      setClusters(res.clusters || []);
    } catch (err: any) {
      if (err.status === 404) {
         toast('Clusters endpoint not implemented in backend yet', 'error');
      } else {
         toast(err.message, 'error');
      }
    } finally {
      setLoading(false);
    }
  };

  const [selectedCluster, setSelectedCluster] = useState<any>(null);
  const [failures, setFailures] = useState<any[]>([]);
  const [failuresLoading, setFailuresLoading] = useState(false);

  const loadFailures = async (cluster: any) => {
    setSelectedCluster(cluster);
    setFailuresLoading(true);
    try {
      const res = await apiGet(`/clusters/${cluster.id}/failures`);
      setFailures(res.failures || []);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setFailuresLoading(false);
    }
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Episodes"
        title="Task Clusters"
        lede="Recurring task patterns, grouped automatically — each cluster tracks its own baseline score and drift."
      />

      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {[0, 1].map((i) => <div key={i} className="ed-card h-56 animate-pulse bg-zinc-50/60" />)}
        </div>
      ) : clusters.length === 0 ? (
        <EmptyState
          icon={<Network size={26} />}
          title="No clusters found"
          hint="Clusters form once your agents accumulate enough episodes for recurring task patterns to emerge."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {clusters.map((c, i) => {
            const regressing = c.drift < -0.1;
            const pct = c.avg_score != null ? Math.round(c.avg_score * 100) : null;
            return (
              <Reveal key={i} delay={i * 60} variant="scale">
                <div className={`ed-card p-6 ${regressing ? 'border-rose-200' : ''}`}>
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <h3 className="text-lg font-semibold text-zinc-900 truncate">{c.label || `Cluster ${c.id}`}</h3>
                    {regressing && (
                      <span className="shrink-0 inline-flex items-center rounded-full bg-rose-50 text-rose-600 border border-rose-100 px-2 py-0.5 text-[11px] font-semibold">
                        Regressing {Math.round(c.drift * 100)}%
                      </span>
                    )}
                  </div>
                  <div className="text-[13px] text-zinc-400 mb-6">{c.episode_count} episodes</div>

                  <div className="flex items-center gap-4 mb-5">
                    <div className="ed-stat text-4xl" style={{ color: scoreColor(c.avg_score) }}>
                      {pct != null ? `${pct}%` : 'N/A'}
                    </div>
                    <div className="flex-1 h-1.5 rounded-full bg-zinc-100 overflow-hidden">
                      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${(c.avg_score || 0) * 100}%`, background: scoreColor(c.avg_score) }} />
                    </div>
                  </div>

                  <div className="text-[13px] text-zinc-400 mb-6">
                    Most common failure: <span className="text-zinc-700 font-medium">{c.top_failing_tool || 'unknown'}</span>
                  </div>

                  <div className="flex gap-2.5">
                    <Link href={`/episodes?cluster=${c.id}`} className="flex-1 inline-flex items-center justify-center h-9 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors">
                      View episodes
                    </Link>
                    <button className="flex-1 inline-flex items-center justify-center h-9 rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors" onClick={() => loadFailures(c)}>
                      Failure detail
                    </button>
                  </div>
                </div>
              </Reveal>
            );
          })}
        </div>
      )}

      {selectedCluster && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/50 backdrop-blur-sm p-4 animate-in fade-in duration-200"
          onClick={() => setSelectedCluster(null)}
        >
          <div
            className="ed-card w-[600px] max-w-[92vw] max-h-[82vh] overflow-y-auto p-6 shadow-2xl animate-in zoom-in-95 fade-in duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-5">
              <div>
                <div className="ed-kicker mb-1">Cluster failures</div>
                <h2 className="text-lg font-semibold text-zinc-900">{selectedCluster.label}</h2>
              </div>
              <button
                className="inline-flex items-center justify-center h-8 w-8 rounded-lg border border-zinc-200 text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50 transition-colors"
                onClick={() => setSelectedCluster(null)}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>

            {failuresLoading ? (
              <div className="ed-card h-24 animate-pulse bg-zinc-50/60" />
            ) : failures.length === 0 ? (
              <div className="text-sm text-zinc-400 py-8 text-center">No failing steps recorded in this cluster.</div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {failures.map((f, i) => (
                  <div key={i} className="rounded-lg border border-zinc-200 p-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="font-mono text-sm font-semibold text-zinc-900">{f.tool_name}</span>
                      <span className="inline-flex items-center rounded-full bg-rose-50 text-rose-600 border border-rose-100 px-2 py-0.5 text-[11px] font-semibold">{f.count} occurrences</span>
                    </div>
                    <div className="text-[13px] text-zinc-400">
                      Step {f.step_index} · category {f.error_category || 'unknown'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
