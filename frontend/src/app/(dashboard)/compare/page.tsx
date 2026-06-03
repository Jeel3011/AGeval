'use client';
import { useEffect, useState, Suspense } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, outcomeClass, fmtLatency } from '@/lib/utils';
import { useSearchParams, useRouter } from 'next/navigation';
import { CheckCircle, XCircle, ArrowLeftRight, GitCompare } from 'lucide-react';
import { PageHeader } from '@/components/ui/PageHeader';
import { PageContainer, EmptyState } from '@/components/ui/EmptyState';

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

  const [diff, setDiff] = useState<any>(null);

  const loadCompare = async (a: string, b: string) => {
    setLoading(true);
    try {
      const [detA, detB, cmp] = await Promise.all([
        apiGet(`/episodes/${encodeURIComponent(a)}`),
        apiGet(`/episodes/${encodeURIComponent(b)}`),
        // Real backend pairwise diff (§2.4): LCS path alignment + optional LLM verdict.
        apiGet(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`).catch(() => null),
      ]);
      setData({ a: detA, b: detB });
      setDiff(cmp);
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
    <PageContainer>
      <PageHeader
        kicker="Episodes"
        title="Compare Episodes"
        lede="Two runs, side by side — aligned tool trajectories, score deltas, and an optional judge verdict."
      />

      <div className="flex items-end gap-4 mb-6">
        <div className="flex-1">
          <label className="block mb-1.5 text-[13px] font-medium text-zinc-500">Episode A</label>
          <select className="w-full h-10 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={epA} onChange={e => setEpA(e.target.value)}>
            <option value="">Select an episode…</option>
            {recentEps.map(e => <option key={e.episode_id} value={e.episode_id}>{e.task} ({e.episode_id})</option>)}
          </select>
        </div>

        <button className="inline-flex items-center justify-center h-10 w-10 rounded-lg border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900 transition-colors" onClick={handleSwap} title="Swap A and B">
          <ArrowLeftRight size={16} />
        </button>

        <div className="flex-1">
          <label className="block mb-1.5 text-[13px] font-medium text-zinc-500">Episode B</label>
          <select className="w-full h-10 rounded-lg border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 transition" value={epB} onChange={e => setEpB(e.target.value)}>
            <option value="">Select an episode…</option>
            {recentEps.map(e => <option key={e.episode_id} value={e.episode_id}>{e.task} ({e.episode_id})</option>)}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="ed-card h-96 animate-pulse bg-zinc-50/60" />
      ) : data ? (
        <div className="ed-card overflow-hidden p-0">
          <div className="flex border-b border-zinc-200 bg-zinc-50/60">
            <div className="flex-1 p-6 border-r border-zinc-200">
              <div className="ed-kicker mb-1">Episode A score</div>
              <div className="ed-stat text-3xl" style={{ color: scoreColor(rulesA) }}>{rulesA != null ? `${Math.round(rulesA*100)}%` : 'N/A'}</div>
              <div className="mt-2"><span className={`badge badge-${outcomeClass(data.a.episode.outcome)}`}>{data.a.episode.outcome}</span></div>
            </div>
            <div className="flex-1 p-6">
              <div className="ed-kicker mb-1">Episode B score</div>
              <div className="ed-stat text-3xl" style={{ color: scoreColor(rulesB) }}>{rulesB != null ? `${Math.round(rulesB*100)}%` : 'N/A'}</div>
              <div className="mt-2"><span className={`badge badge-${outcomeClass(data.b.episode.outcome)}`}>{data.b.episode.outcome}</span></div>
            </div>
          </div>
          
          {/* Pairwise diff from the backend (§2.4): path alignment, deltas, verdict */}
          {diff && (
            <div style={{padding:24, borderBottom:'1px solid var(--border)', display:'flex', flexDirection:'column', gap:16}}>
              {diff.llm_verdict && (
                <div style={{padding:12, border:'1px solid var(--accent)', borderRadius:'var(--radius-sm)', fontSize:13}}>
                  <b style={{textTransform:'uppercase'}}>Judge verdict: {diff.llm_verdict.winner === 'tie' ? 'tie' : `Episode ${diff.llm_verdict.winner.toUpperCase()} wins`}</b>
                  <div style={{color:'var(--text-muted)', marginTop:4}}>{diff.llm_verdict.reasoning}</div>
                </div>
              )}
              <div style={{display:'flex', gap:24, flexWrap:'wrap', fontSize:13}}>
                <span style={{color:'var(--text-muted)'}}>Edit distance: <b style={{color:'var(--text)'}}>{diff.edit_distance}</b></span>
                <span style={{color:'var(--text-muted)'}}>Step delta: <b style={{color:'var(--text)'}}>{diff.step_delta > 0 ? '+' : ''}{diff.step_delta}</b></span>
                {Object.entries(diff.score_deltas || {}).map(([s, d]: [string, any]) => (
                  <span key={s} style={{color:'var(--text-muted)'}}>{s}: <b style={{color: d.delta == null ? 'var(--text-muted)' : d.delta < 0 ? 'var(--danger)' : d.delta > 0 ? 'var(--success)' : 'var(--text)'}}>{d.delta == null ? '—' : `${d.delta >= 0 ? '+' : ''}${d.delta.toFixed(2)}`}</b></span>
                ))}
              </div>
              {/* Tool-sequence alignment */}
              <div style={{display:'flex', flexWrap:'wrap', gap:6, alignItems:'center'}}>
                {(diff.sequence_diff || []).map((op: any, i: number) => {
                  const color = op.op === 'same' ? 'var(--text-muted)' : op.op === 'a_only' ? 'var(--danger)' : 'var(--success)';
                  const prefix = op.op === 'a_only' ? '− ' : op.op === 'b_only' ? '+ ' : '';
                  return (
                    <span key={i} style={{fontFamily:'monospace', fontSize:11, padding:'2px 6px', borderRadius:4, border:`1px solid ${color}`, color}}>
                      {prefix}{op.tool}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

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
        <EmptyState
          icon={<GitCompare size={26} />}
          title="Pick two episodes"
          hint="Choose Episode A and Episode B above to align their trajectories and see exactly where they diverge."
        />
      )}
    </PageContainer>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="px-8 py-8"><div className="ed-card h-96 animate-pulse bg-zinc-50/60" /></div>}>
      <CompareContent />
    </Suspense>
  );
}
