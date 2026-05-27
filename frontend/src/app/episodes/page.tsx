'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency, fmtDate } from '@/lib/utils';
import { Search, ArrowLeftRight, SearchCode } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

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
    <div>
      <header style={{marginBottom: 24}}>
        <h1 style={{margin:0, fontSize:24, fontWeight:600}}>Episodes</h1>
      </header>

      <div style={{display:'flex', gap:12, marginBottom:24, flexWrap:'wrap'}}>
        <select className="input" style={{width: 150}} value={agentFilter} onChange={e => setAgentFilter(e.target.value)}>
          <option value="">All Agents</option>
          {agents.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <select className="input" style={{width: 150}} value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)}>
          <option value="">All Outcomes</option>
          <option value="success">Success</option>
          <option value="partial">Partial</option>
          <option value="failure">Failure</option>
        </select>
        <select className="input" style={{width: 150}} value={scoreFilter} onChange={e => setScoreFilter(e.target.value)}>
          <option value="">All Scores</option>
          <option value="high">High (≥0.8)</option>
          <option value="medium">Medium (0.5–0.79)</option>
          <option value="low">Low (&lt;0.5)</option>
          <option value="unscored">Unscored</option>
        </select>
        <div style={{position:'relative', flex:1, minWidth:200}}>
          <Search size={16} style={{position:'absolute', left:12, top:'50%', transform:'translateY(-50%)', color:'var(--text-muted)'}} />
          <input className="input" style={{paddingLeft:36}} placeholder="Search task or ID..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
        </div>
      </div>

      <div className="card" style={{padding:0, overflow:'hidden'}}>
        {loading ? (
          <div style={{padding:24}}><div className="skeleton" style={{height: 400}} /></div>
        ) : filtered.length === 0 ? (
          <div style={{padding:64, textAlign:'center', color:'var(--text-muted)'}}>No episodes found.</div>
        ) : (
          <table style={{width:'100%', borderCollapse:'collapse', textAlign:'left'}}>
            <thead>
              <tr style={{borderBottom:'1px solid var(--border)', background:'rgba(255,255,255,0.02)'}}>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Score</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>ID</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Agent</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Task</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Outcome</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Steps</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Latency</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13}}>Date</th>
                <th style={{padding:'12px 24px', fontWeight:500, color:'var(--text-muted)', fontSize:13, width: 100}}></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, i) => (
                <tr key={e.episode_id} style={{borderBottom: i < filtered.length-1 ? '1px solid var(--border)' : 'none', cursor:'pointer'}} onClick={() => router.push(`/episodes/${e.episode_id}`)}>
                  <td style={{padding:'12px 24px'}}>
                    <span style={{color: scoreColor(e.score), fontWeight:600}}>
                      {e.score != null ? `● ${e.score.toFixed(2)}` : '–'}
                    </span>
                  </td>
                  <td style={{padding:'12px 24px', fontFamily:'monospace', color:'var(--accent)', fontSize:13}}>{e.episode_id}</td>
                  <td style={{padding:'12px 24px', fontSize:14}}>{e.agent_id || '—'}</td>
                  <td style={{padding:'12px 24px', fontSize:14, maxWidth:200, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}} title={e.task}>
                    {e.task || '—'}
                  </td>
                  <td style={{padding:'12px 24px'}}><span className={`badge badge-${outcomeClass(e.outcome)}`}>{e.outcome}</span></td>
                  <td style={{padding:'12px 24px', fontSize:14, color:'var(--text-muted)'}}>{e.total_steps ?? '—'}</td>
                  <td style={{padding:'12px 24px', fontSize:14, color:'var(--text-muted)'}}>{fmtLatency(e.total_latency_ms)}</td>
                  <td style={{padding:'12px 24px', fontSize:14, color:'var(--text-muted)'}}>{fmtDate(e.created_at)}</td>
                  <td style={{padding:'12px 24px'}}>
                    <div style={{display:'flex', gap:8}}>
                      <button className="btn-ghost" style={{padding:4, borderRadius:'var(--radius-sm)'}} onClick={ev => handleCompare(ev, e.episode_id)} title="Compare"><ArrowLeftRight size={14}/></button>
                      <button className="btn-ghost" style={{padding:4, borderRadius:'var(--radius-sm)'}} onClick={ev => handleRecall(ev, e.task || '')} title="Find Similar"><SearchCode size={14}/></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
