'use client';
import { useState, Suspense, useEffect } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency } from '@/lib/utils';
import { useSearchParams, useRouter } from 'next/navigation';
import { Search, ArrowLeftRight } from 'lucide-react';
import Link from 'next/link';

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
    <div>
      <header style={{marginBottom: 24}}>
        <h1 style={{margin:0, fontSize:24, fontWeight:600}}>Recall (Semantic Search)</h1>
        <p style={{margin:0, color:'var(--text-muted)'}}>Find past runs similar to any task using embeddings.</p>
      </header>

      <div style={{display:'flex', gap:12, marginBottom:16}}>
        <div style={{position:'relative', flex:1}}>
          <Search size={16} style={{position:'absolute', left:12, top:'50%', transform:'translateY(-50%)', color:'var(--text-muted)'}} />
          <input 
            className="input" 
            style={{paddingLeft:36}} 
            placeholder="Describe a task..." 
            value={search} 
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
          />
        </div>
        <button className="btn btn-primary" onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      <div style={{display:'flex', gap:12, marginBottom:32, paddingBottom:24, borderBottom:'1px solid var(--border)'}}>
        <input className="input" style={{width: 150}} placeholder="Agent ID..." value={agentFilter} onChange={e=>setAgentFilter(e.target.value)} />
        <select className="input" style={{width: 150}} value={outcomeFilter} onChange={e=>setOutcomeFilter(e.target.value)}>
          <option value="">All Outcomes</option>
          <option value="success">Success</option>
          <option value="partial">Partial</option>
          <option value="failure">Failure</option>
        </select>
        <select className="input" style={{width: 150}} value={minScore} onChange={e=>setMinScore(e.target.value)}>
          <option value="">Min Score</option>
          <option value="0.8">≥ 0.8</option>
          <option value="0.5">≥ 0.5</option>
        </select>
      </div>

      {loading ? (
        <div style={{display:'flex', flexDirection:'column', gap:16}}>
          <div className="skeleton" style={{height: 100}} />
          <div className="skeleton" style={{height: 100}} />
        </div>
      ) : searched ? (
        results.length === 0 ? (
          <div style={{padding:40, textAlign:'center', color:'var(--text-muted)', border:'1px dashed var(--border)', borderRadius:'var(--radius-md)'}}>
            {emptyReason}
          </div>
        ) : (
          <div style={{display:'flex', flexDirection:'column', gap:16}}>
            {results.map((r, i) => (
              <div key={i} className="card" style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                <div>
                  <h3 style={{margin:'0 0 8px 0', fontSize:16, fontWeight:500}}>{r.episode.task || 'No task'}</h3>
                  <div style={{display:'flex', gap:12, fontSize:13, color:'var(--text-muted)', alignItems:'center'}}>
                    <span style={{fontFamily:'monospace', color:'var(--accent)'}}>{r.episode.episode_id}</span>
                    <span>· {r.episode.agent_id}</span>
                    <span className={`badge badge-${outcomeClass(r.episode.outcome)}`}>{r.episode.outcome}</span>
                    <span>· {r.episode.total_steps ?? 0} steps</span>
                    <span>· {fmtLatency(r.episode.total_latency_ms)}</span>
                  </div>
                </div>
                <div style={{display:'flex', alignItems:'center', gap:24}}>
                  <div style={{textAlign:'right'}}>
                     <div style={{fontSize:20, fontWeight:600, color: scoreColor(r.episode.score)}}>{r.episode.score != null ? `${Math.round(r.episode.score*100)}%` : 'N/A'}</div>
                     <div style={{fontSize:11, color:'var(--text-muted)'}}>Score</div>
                  </div>
                  <div style={{textAlign:'right', minWidth: 60}}>
                     <div style={{fontSize:20, fontWeight:600}}>{Math.round(r.similarity * 100)}%</div>
                     <div style={{fontSize:11, color:'var(--text-muted)'}}>Match</div>
                  </div>
                  <div style={{display:'flex', flexDirection:'column', gap:8}}>
                     <Link href={`/episodes/${r.episode.episode_id}`} className="btn btn-ghost" style={{padding:'4px 12px', fontSize:12, textAlign:'center'}}>Detail</Link>
                     <button className="btn btn-ghost" style={{padding:'4px 12px', fontSize:12, display:'flex', gap:6, alignItems:'center'}} onClick={e => handleCompareB(e, r.episode.episode_id)}>
                       <ArrowLeftRight size={12}/> Compare→B
                     </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        <div style={{padding:40, textAlign:'center', color:'var(--text-muted)', border:'1px dashed var(--border)', borderRadius:'var(--radius-md)'}}>
          Enter a task description above to find similar historical episodes.
        </div>
      )}
    </div>
  );
}

export default function RecallPage() {
  return (
    <Suspense fallback={<div className="skeleton" style={{height: 400}} />}>
      <RecallContent />
    </Suspense>
  );
}
