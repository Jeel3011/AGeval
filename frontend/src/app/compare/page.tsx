'use client';
import { useEffect, useState, Suspense } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency } from '@/lib/utils';
import { useSearchParams, useRouter } from 'next/navigation';
import { CheckCircle, XCircle, ArrowLeftRight } from 'lucide-react';

function CompareContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();
  
  const queryA = searchParams.get('a') || '';
  const queryB = searchParams.get('b') || '';
  
  const [epA, setEpA] = useState(queryA);
  const [epB, setEpB] = useState(queryB);
  
  const [recentEps, setRecentEps] = useState<any[]>([]);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expandedA, setExpandedA] = useState<Set<number>>(new Set());
  const [expandedB, setExpandedB] = useState<Set<number>>(new Set());

  useEffect(() => {
    // Load recent episodes for dropdown
    apiGet('/episodes?limit=50').then(res => {
      setRecentEps(res.episodes || []);
    }).catch(err => toast('Failed to load recent episodes', 'error'));
  }, []);

  useEffect(() => {
    if (epA && epB) {
      router.replace(`/compare?a=${encodeURIComponent(epA)}&b=${encodeURIComponent(epB)}`);
      loadCompare(epA, epB);
    }
  }, [epA, epB]);

  const loadCompare = async (a: string, b: string) => {
    setLoading(true);
    try {
      const [detA, detB] = await Promise.all([
        apiGet(`/episodes/${encodeURIComponent(a)}`),
        apiGet(`/episodes/${encodeURIComponent(b)}`)
      ]);
      setData({ a: detA, b: detB });
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSwap = () => {
    const temp = epA;
    setEpA(epB);
    setEpB(temp);
  };

  const renderTimeline = (steps: any[], expanded: Set<number>, setExpanded: any, divergeIdx: number) => {
    if (!steps?.length) return <div style={{color:'var(--text-muted)'}}>No steps.</div>;
    return (
      <div style={{display:'flex', flexDirection:'column', gap:8}}>
        {steps.map((s, i) => {
          const isDiv = i === divergeIdx;
          const exp = expanded.has(i);
          return (
            <div key={i}>
              {isDiv && <div style={{textAlign:'center', color:'var(--warning)', fontSize:12, fontWeight:600, margin:'12px 0'}}>◄ DIVERGES HERE ━━━━━━━━</div>}
              <div 
                style={{
                  border:`1px solid ${isDiv ? 'var(--warning)' : 'var(--border)'}`, 
                  borderRadius:'var(--radius-sm)', 
                  overflow:'hidden',
                  background: isDiv ? 'rgba(234,179,8,0.05)' : 'transparent'
                }}
              >
                <div 
                  style={{padding:8, display:'flex', alignItems:'center', justifyContent:'space-between', cursor:'pointer'}}
                  onClick={() => {
                    const next = new Set(expanded);
                    if (next.has(i)) next.delete(i); else next.add(i);
                    setExpanded(next);
                  }}
                >
                  <div style={{display:'flex', alignItems:'center', gap:8, fontSize:13}}>
                    <span style={{color:'var(--text-muted)'}}>{i+1}.</span>
                    {s.success ? <CheckCircle size={14} color="var(--success)" /> : <XCircle size={14} color="var(--danger)" />}
                    <span style={{fontFamily:'monospace'}}>{s.tool_name}</span>
                  </div>
                  {isDiv && <span className="badge badge-warning">Diverged</span>}
                </div>
                {exp && (
                  <div style={{padding:12, borderTop:`1px solid ${isDiv ? 'rgba(234,179,8,0.2)' : 'var(--border)'}`, fontSize:12, background:'rgba(0,0,0,0.2)'}}>
                    {s.reasoning && <div style={{marginBottom:8}}><b>Reasoning:</b> {s.reasoning}</div>}
                    {s.tool_output != null && (
                      <div><b>Output:</b> <pre style={{margin:0, padding:4, background:'rgba(255,255,255,0.05)', borderRadius:4, overflowX:'auto'}}>{JSON.stringify(s.tool_output)}</pre></div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  let divergeIdx = -1;
  if (data?.a?.steps && data?.b?.steps) {
    const sA = data.a.steps;
    const sB = data.b.steps;
    const maxLen = Math.max(sA.length, sB.length);
    for (let i = 0; i < maxLen; i++) {
      if (!sA[i] || !sB[i] || sA[i].tool_name !== sB[i].tool_name || sA[i].success !== sB[i].success) {
        divergeIdx = i;
        break;
      }
    }
  }

  const rulesA = data?.a?.scores?.find((s:any)=>s.scorer==='rules')?.score;
  const rulesB = data?.b?.scores?.find((s:any)=>s.scorer==='rules')?.score;

  return (
    <div>
      <header style={{marginBottom: 24}}>
        <h1 style={{margin:0, fontSize:24, fontWeight:600}}>Compare Episodes</h1>
      </header>

      <div style={{display:'flex', gap:16, alignItems:'center', marginBottom:24}}>
        <div style={{flex:1}}>
          <label style={{display:'block', marginBottom:8, fontSize:14, fontWeight:500, color:'var(--text-muted)'}}>Episode A</label>
          <select className="input" value={epA} onChange={e => setEpA(e.target.value)}>
            <option value="">Select an episode...</option>
            {recentEps.map(e => <option key={e.episode_id} value={e.episode_id}>{e.task} ({e.episode_id})</option>)}
          </select>
        </div>
        
        <button className="btn-ghost" style={{padding:8, borderRadius:'var(--radius-sm)', marginTop:24}} onClick={handleSwap} title="Swap A and B">
          <ArrowLeftRight size={16} />
        </button>

        <div style={{flex:1}}>
          <label style={{display:'block', marginBottom:8, fontSize:14, fontWeight:500, color:'var(--text-muted)'}}>Episode B</label>
          <select className="input" value={epB} onChange={e => setEpB(e.target.value)}>
            <option value="">Select an episode...</option>
            {recentEps.map(e => <option key={e.episode_id} value={e.episode_id}>{e.task} ({e.episode_id})</option>)}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="skeleton" style={{height: 400}} />
      ) : data ? (
        <div className="card" style={{padding:0, overflow:'hidden'}}>
          <div style={{display:'flex', borderBottom:'1px solid var(--border)', background:'rgba(255,255,255,0.02)'}}>
            <div style={{flex:1, padding:24, borderRight:'1px solid var(--border)'}}>
              <div style={{fontSize:13, color:'var(--text-muted)'}}>Episode A Score</div>
              <div style={{fontSize:28, fontWeight:600, color: scoreColor(rulesA)}}>{rulesA != null ? `${Math.round(rulesA*100)}%` : 'N/A'}</div>
              <div style={{marginTop:8}}>
                 <span className={`badge badge-${outcomeClass(data.a.episode.outcome)}`}>{data.a.episode.outcome}</span>
              </div>
            </div>
            <div style={{flex:1, padding:24}}>
              <div style={{fontSize:13, color:'var(--text-muted)'}}>Episode B Score</div>
              <div style={{fontSize:28, fontWeight:600, color: scoreColor(rulesB)}}>{rulesB != null ? `${Math.round(rulesB*100)}%` : 'N/A'}</div>
              <div style={{marginTop:8}}>
                 <span className={`badge badge-${outcomeClass(data.b.episode.outcome)}`}>{data.b.episode.outcome}</span>
              </div>
            </div>
          </div>
          
          <div style={{display:'flex'}}>
            <div style={{flex:1, padding:24, borderRight:'1px solid var(--border)', overflowY:'auto', maxHeight:600}}>
              {renderTimeline(data.a.steps, expandedA, setExpandedA, divergeIdx)}
            </div>
            <div style={{flex:1, padding:24, overflowY:'auto', maxHeight:600}}>
               {renderTimeline(data.b.steps, expandedB, setExpandedB, divergeIdx)}
            </div>
          </div>
        </div>
      ) : (
        <div style={{padding:40, textAlign:'center', color:'var(--text-muted)', border:'1px dashed var(--border)', borderRadius:'var(--radius-md)'}}>
          Select two episodes above to compare them side-by-side.
        </div>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="skeleton" style={{height: 400}} />}>
      <CompareContent />
    </Suspense>
  );
}
