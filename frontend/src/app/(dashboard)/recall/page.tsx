'use client';
import { useState, Suspense, useEffect } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency } from '@/lib/utils';
import { useSearchParams, useRouter } from 'next/navigation';
import { Search, ArrowLeftRight } from 'lucide-react';
import Link from 'next/link';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';
import { Reveal } from '@/components/ui/Reveal';

function RecallContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();
  
  const queryQ = searchParams.get('q') || '';
  
  const [search, setSearch] = useState(queryQ);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [emptyReason, setEmptyReason] = useState('');

  // Filters
  const [agentFilter, setAgentFilter] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState(searchParams.get('outcome') || '');
  const [minScore, setMinScore] = useState('');

  useEffect(() => {
    if (queryQ && !searched) {
      handleSearch();
    }
  }, [queryQ]);

  const handleSearch = async () => {
    if (!search.trim()) return;
    setLoading(true);
    setSearched(true);
    router.replace(`/recall?q=${encodeURIComponent(search)}`);
    
    try {
      let path = `/recall?task=${encodeURIComponent(search)}`;
      if (agentFilter) path += `&agent_id=${encodeURIComponent(agentFilter)}`;
      
      const data = await apiGet(path);
      
      let res = data.results || [];
      
      // Client side filters for outcome and score
      if (outcomeFilter) res = res.filter((r:any) => r.episode.outcome === outcomeFilter);
      if (minScore) res = res.filter((r:any) => r.episode.score >= parseFloat(minScore));

      setResults(res);
      
      if (res.length === 0) {
        if (!data.embeddings_exist) {
          setEmptyReason("Embeddings haven't been generated yet. Make sure OPENAI_API_KEY is set on your server and the worker is running.");
        } else {
          setEmptyReason("No similar episodes found matching your criteria.");
        }
      }
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCompareB = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    router.push(`/compare?b=${encodeURIComponent(id)}`);
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Episodes"
        title="Semantic Recall"
        lede="Find past runs similar to any task using embeddings — search by intent, not keywords."
      />

      <div className="flex gap-3 mb-4">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            className="w-full h-11 rounded-xl border border-zinc-200 bg-white pl-10 pr-3 text-[15px] text-zinc-900 outline-none focus:border-zinc-900 focus:ring-2 focus:ring-zinc-900/10 transition"
            placeholder="Describe a task…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
          />
        </div>
        <button
          className="inline-flex items-center gap-2 h-11 px-6 rounded-xl bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-60"
          onClick={handleSearch}
          disabled={loading}
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      <div className="flex flex-wrap gap-3 mb-8 pb-6 border-b border-zinc-200">
        <input className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" placeholder="Agent ID…" value={agentFilter} onChange={e=>setAgentFilter(e.target.value)} />
        <select className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={outcomeFilter} onChange={e=>setOutcomeFilter(e.target.value)}>
          <option value="">All outcomes</option>
          <option value="success">Success</option>
          <option value="partial">Partial</option>
          <option value="failure">Failure</option>
        </select>
        <select className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={minScore} onChange={e=>setMinScore(e.target.value)}>
          <option value="">Min score</option>
          <option value="0.8">≥ 0.8</option>
          <option value="0.5">≥ 0.5</option>
        </select>
      </div>

      {loading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map(i => <div key={i} className="ed-card h-24 animate-pulse bg-zinc-50/60" />)}
        </div>
      ) : searched ? (
        results.length === 0 ? (
          <EmptyState icon={<Search size={26} />} title="No matches" hint={emptyReason} />
        ) : (
          <div className="flex flex-col gap-3">
            {results.map((r, i) => (
              <Reveal key={i} delay={i * 45}>
                <div className="ed-card flex items-center justify-between gap-5 p-5">
                  <div className="min-w-0">
                    <h3 className="text-[15px] font-medium text-zinc-900 mb-1.5 truncate">{r.episode.task || 'No task'}</h3>
                    <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-zinc-400">
                      <span className="font-mono text-zinc-500">{r.episode.episode_id}</span>
                      <span>· {r.episode.agent_id}</span>
                      <span className={`badge badge-${outcomeClass(r.episode.outcome)}`}>{r.episode.outcome}</span>
                      <span>· {r.episode.total_steps ?? 0} steps</span>
                      <span>· {fmtLatency(r.episode.total_latency_ms)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-6 shrink-0">
                    <div className="text-right">
                      <div className="ed-stat text-xl" style={{ color: scoreColor(r.episode.score) }}>{r.episode.score != null ? `${Math.round(r.episode.score*100)}%` : 'N/A'}</div>
                      <div className="text-[11px] text-zinc-400 mt-0.5">Score</div>
                    </div>
                    <div className="text-right min-w-[56px]">
                      <div className="ed-stat text-xl text-zinc-900">{Math.round(r.similarity * 100)}%</div>
                      <div className="text-[11px] text-zinc-400 mt-0.5">Match</div>
                    </div>
                    <div className="flex flex-col gap-2">
                      <Link href={`/episodes/${r.episode.episode_id}`} className="inline-flex items-center justify-center h-8 px-3 rounded-lg border border-zinc-200 bg-white text-xs font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors">Detail</Link>
                      <button className="inline-flex items-center gap-1.5 justify-center h-8 px-3 rounded-lg border border-zinc-200 bg-white text-xs font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors" onClick={e => handleCompareB(e, r.episode.episode_id)}>
                        <ArrowLeftRight size={12}/> Compare → B
                      </button>
                    </div>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        )
      ) : (
        <EmptyState
          icon={<Search size={26} />}
          title="Search your episode history"
          hint="Enter a task description above to find the most semantically similar historical episodes."
        />
      )}
    </PageContainer>
  );
}

export default function RecallPage() {
  return (
    <Suspense fallback={<div className="px-8 py-8"><div className="ed-card h-96 animate-pulse bg-zinc-50/60" /></div>}>
      <RecallContent />
    </Suspense>
  );
}
