'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency, fmtDate } from '@/lib/utils';
import { Search, ArrowLeftRight, SearchCode, Layers } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';

export default function EpisodesPage() {
  const { toast } = useToast();
  const router = useRouter();
  const [episodes, setEpisodes] = useState<any[]>([]);
  const [filtered, setFiltered] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Filters
  const [agentFilter, setAgentFilter] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('');
  const [scoreFilter, setScoreFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const [agents, setAgents] = useState<string[]>([]);

  useEffect(() => {
    loadEpisodes();
  }, [agentFilter]);

  useEffect(() => {
    filterData();
  }, [episodes, outcomeFilter, scoreFilter, searchQuery]);

  const loadEpisodes = async () => {
    setLoading(true);
    try {
      let path = '/episodes?limit=100';
      if (agentFilter) path += `&agent_id=${encodeURIComponent(agentFilter)}`;
      const data = await apiGet(path);
      const eps = data.episodes || [];
      setEpisodes(eps);
      
      const uniqueAgents = Array.from(new Set(eps.map((e:any) => e.agent_id))).filter(Boolean) as string[];
      setAgents(uniqueAgents);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const filterData = () => {
    let res = episodes;
    if (outcomeFilter) res = res.filter(e => e.outcome === outcomeFilter);
    if (scoreFilter) {
      res = res.filter(e => {
        const s = e.score;
        if (scoreFilter === 'unscored') return s == null;
        if (s == null) return false;
        if (scoreFilter === 'high') return s >= 0.8;
        if (scoreFilter === 'medium') return s >= 0.5 && s < 0.8;
        if (scoreFilter === 'low') return s < 0.5;
        return true;
      });
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      res = res.filter(e => (e.task || '').toLowerCase().includes(q) || (e.episode_id || '').toLowerCase().includes(q));
    }
    setFiltered(res);
  };

  const handleCompare = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    router.push(`/compare?a=${encodeURIComponent(id)}`);
  };

  const handleRecall = (e: React.MouseEvent, task: string) => {
    e.stopPropagation();
    router.push(`/recall?q=${encodeURIComponent(task)}`);
  };

  return (
    <PageContainer>
      <PageHeader
        kicker="Episodes"
        title="Episodes"
        lede="Every recorded agent run — its trajectory, outcome, and score. The system of record."
      />

      <div className="flex flex-wrap gap-3 mb-6">
        <select className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={agentFilter} onChange={e => setAgentFilter(e.target.value)}>
          <option value="">All agents</option>
          {agents.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <select className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)}>
          <option value="">All outcomes</option>
          <option value="success">Success</option>
          <option value="partial">Partial</option>
          <option value="failure">Failure</option>
        </select>
        <select className="h-9 w-40 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={scoreFilter} onChange={e => setScoreFilter(e.target.value)}>
          <option value="">All scores</option>
          <option value="high">High (≥0.8)</option>
          <option value="medium">Medium (0.5–0.79)</option>
          <option value="low">Low (&lt;0.5)</option>
          <option value="unscored">Unscored</option>
        </select>
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input className="w-full h-9 rounded-lg border border-zinc-200 bg-white pl-10 pr-3 text-sm outline-none focus:border-zinc-400 transition" placeholder="Search task or ID…" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
        </div>
      </div>

      {loading ? (
        <div className="ed-card h-96 animate-pulse bg-zinc-50/60" />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Layers size={26} />}
          title="No episodes found"
          hint="Run an instrumented agent — episodes appear here the moment they're recorded. Try clearing filters if you expected results."
        />
      ) : (
        <div className="ed-card overflow-hidden p-0">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50/60">
                {['Score','ID','Agent','Task','Outcome','Steps','Latency','Date',''].map((h, i) => (
                  <th key={i} className="px-6 py-3 font-medium text-zinc-400 text-xs uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr
                  key={e.episode_id}
                  className="border-b border-zinc-100 last:border-0 cursor-pointer hover:bg-zinc-50/80 transition-colors"
                  onClick={() => router.push(`/episodes/${e.episode_id}`)}
                >
                  <td className="px-6 py-3.5">
                    <span className="font-semibold tabular-nums" style={{ color: scoreColor(e.score) }}>
                      {e.score != null ? `● ${e.score.toFixed(2)}` : '–'}
                    </span>
                  </td>
                  <td className="px-6 py-3.5 font-mono text-zinc-500 text-[13px]">{e.episode_id}</td>
                  <td className="px-6 py-3.5 text-sm text-zinc-700">{e.agent_id || '—'}</td>
                  <td className="px-6 py-3.5 text-sm text-zinc-700 max-w-[220px] truncate" title={e.task}>{e.task || '—'}</td>
                  <td className="px-6 py-3.5"><span className={`badge badge-${outcomeClass(e.outcome)}`}>{e.outcome}</span></td>
                  <td className="px-6 py-3.5 text-sm text-zinc-400 tabular-nums">{e.total_steps ?? '—'}</td>
                  <td className="px-6 py-3.5 text-sm text-zinc-400 tabular-nums">{fmtLatency(e.total_latency_ms)}</td>
                  <td className="px-6 py-3.5 text-sm text-zinc-400">{fmtDate(e.created_at)}</td>
                  <td className="px-6 py-3.5">
                    <div className="flex gap-1.5">
                      <button className="inline-flex items-center justify-center h-7 w-7 rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors" onClick={ev => handleCompare(ev, e.episode_id)} title="Compare"><ArrowLeftRight size={14}/></button>
                      <button className="inline-flex items-center justify-center h-7 w-7 rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors" onClick={ev => handleRecall(ev, e.task || '')} title="Find similar"><SearchCode size={14}/></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageContainer>
  );
}
