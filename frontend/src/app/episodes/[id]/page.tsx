'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor, fmtLatency, outcomeClass } from '@/lib/utils';
import { ChevronRight, Copy, RefreshCw, MessageSquare, Code, CheckCircle, XCircle } from 'lucide-react';
import Link from 'next/link';

export default function EpisodeDetail({ params }: { params: { id: string } }) {
  const { id } = params;
  const { toast } = useToast();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  useEffect(() => {
    loadData();
    let pollTimer: any;
    if (data?.job && data.job.status !== 'done' && data.job.status !== 'failed') {
      pollTimer = setTimeout(loadData, 3000);
    }
    return () => clearTimeout(pollTimer);
  }, [id, data?.job?.status]);

  const loadData = async () => {
    try {
      const res = await apiGet(`/episodes/${encodeURIComponent(id)}`);
      setData(res);
    } catch (err: any) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCopyId = () => {
    navigator.clipboard.writeText(id);
    toast('Copied ID to clipboard', 'success');
  };

  const handleRescore = async () => {
    toast('Not implemented in backend yet', 'error');
  };

  const toggleStep = (idx: number) => {
    const next = new Set(expandedSteps);
    if (next.has(idx)) next.delete(idx);
    else next.add(idx);
    setExpandedSteps(next);
  };

  if (loading && !data) {
    return <div style={{padding:40}}><div className="skeleton" style={{height:400}} /></div>;
  }
  if (!data) return <div style={{padding:40}}>Episode not found.</div>;

  const { episode, steps, scores, job } = data;
  const rulesScore = scores?.find((s:any) => s.scorer === 'rules');
  const judgeScore = scores?.find((s:any) => s.scorer === 'llm_judge');

  return (
    <div>
      <header style={{marginBottom: 32}}>
        <div style={{display:'flex', alignItems:'center', gap:8, color:'var(--text-muted)', fontSize:14, marginBottom:16}}>
          <Link href="/episodes" style={{textDecoration:'underline'}}>Episodes</Link>
          <ChevronRight size={14} />
          <span style={{color:'var(--accent)', fontFamily:'monospace'}}>{id}</span>
          <button className="btn-ghost" style={{padding:4, display:'flex', alignItems:'center', borderRadius:'var(--radius-sm)'}} onClick={handleCopyId}><Copy size={12} /></button>
          
          {job && (
            <div style={{marginLeft:'auto', display:'flex', alignItems:'center', gap:6, padding:'4px 12px', borderRadius:16, border:`1px solid ${job.status === 'done' ? 'var(--success)' : job.status === 'failed' ? 'var(--danger)' : 'var(--warning)'}`, color: job.status === 'done' ? 'var(--success)' : job.status === 'failed' ? 'var(--danger)' : 'var(--warning)', fontSize: 12}}>
              Merge & Score: {job.status} {job.status !== 'done' && job.status !== 'failed' && <span style={{display:'inline-block',width:6,height:6,background:'currentColor',borderRadius:'50%',animation:'pulse 1.5s infinite'}}/>}
            </div>
          )}
        </div>
        <h1 style={{margin:0, fontSize:24, fontWeight:600}}>{episode.task || 'No task specified'}</h1>
        <div style={{display:'flex', alignItems:'center', gap:12, marginTop:8}}>
          <span className={`badge badge-${outcomeClass(episode.outcome)}`}>{episode.outcome}</span>
          <span style={{color:'var(--text-muted)', fontSize:14}}>{episode.agent_id}</span>
          <span style={{color:'var(--text-muted)', fontSize:14}}>· {episode.total_steps ?? steps?.length} steps · {fmtLatency(episode.total_latency_ms)}</span>
        </div>
      </header>

      <div style={{display:'grid', gridTemplateColumns:'300px 1fr', gap:24}}>
        <div style={{display:'flex', flexDirection:'column', gap:24}}>
          {/* Rules Score Card */}
          <div className="card">
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16}}>
              <h3 style={{margin:0, fontSize:16}}>Rule-Based Score</h3>
              <button className="btn-ghost" style={{padding:'4px 8px', fontSize:12, display:'flex', gap:4, alignItems:'center'}} onClick={handleRescore}>
                <RefreshCw size={12} /> Re-score
              </button>
            </div>
            
            {rulesScore ? (
              <>
                <div style={{display:'flex', alignItems:'center', gap:12, marginBottom:24}}>
                  <div style={{fontSize:32, fontWeight:700, color: scoreColor(rulesScore.score)}}>{Math.round(rulesScore.score * 100)}%</div>
                  <div style={{flex:1, height:8, background:'rgba(255,255,255,0.1)', borderRadius:4, overflow:'hidden'}}>
                    <div style={{height:'100%', width:`${rulesScore.score * 100}%`, background: scoreColor(rulesScore.score)}} />
                  </div>
                </div>
                
                <div style={{display:'flex', flexDirection:'column', gap:12}}>
                  <ScoreMetric name="Success Rate" val={rulesScore.metrics?.success_rate} desc="% of tool calls that worked" />
                  <ScoreMetric name="Recovery Rate" val={rulesScore.metrics?.recovery_rate} desc="How often it recovered from errors" />
                  <ScoreMetric name="Reasoning" val={rulesScore.metrics?.reasoning_coverage} desc="How often it explained decisions" />
                  <ScoreMetric name="Efficiency" val={rulesScore.metrics?.efficiency_score} desc="Penalizes repeated failed tools" />
                </div>
              </>
            ) : (
              <div style={{color:'var(--text-muted)'}}>No rules score available</div>
            )}
          </div>

          {/* AI Judge Score Card */}
          <div className="card">
            <h3 style={{margin:0, fontSize:16, marginBottom:16}}>AI Judge Score</h3>
            {judgeScore ? (
              <>
                <div style={{display:'flex', alignItems:'center', gap:12, marginBottom:24}}>
                  <div style={{fontSize:32, fontWeight:700, color: scoreColor(judgeScore.score)}}>{Math.round(judgeScore.score * 100)}%</div>
                  <div style={{flex:1, height:8, background:'rgba(255,255,255,0.1)', borderRadius:4, overflow:'hidden'}}>
                    <div style={{height:'100%', width:`${judgeScore.score * 100}%`, background: scoreColor(judgeScore.score)}} />
                  </div>
                </div>
                <div style={{display:'flex', flexDirection:'column', gap:12}}>
                  <ScoreMetric name="Task Complete" val={judgeScore.metrics?.task_completion} desc="Did it achieve the goal?" />
                  <ScoreMetric name="Reasoning Quality" val={judgeScore.metrics?.reasoning_quality} desc="Was CoT coherent?" />
                  <ScoreMetric name="Error Handling" val={judgeScore.metrics?.error_handling} desc="Graceful recovery?" />
                  <ScoreMetric name="Output Quality" val={judgeScore.metrics?.output_quality} desc="Final answer accuracy" />
                </div>
                {judgeScore.metadata?.rationale && (
                  <div style={{marginTop:16, padding:12, background:'rgba(255,255,255,0.05)', borderRadius:'var(--radius-sm)', fontSize:12, fontStyle:'italic', color:'var(--text-muted)'}}>
                    "{judgeScore.metadata.rationale}"
                  </div>
                )}
              </>
            ) : (
              <div style={{color:'var(--text-muted)'}}>No AI judge score</div>
            )}
          </div>
        </div>

        <div className="card">
          <h3 style={{margin:0, fontSize:16, marginBottom:16}}>Step Timeline</h3>
          {!steps?.length ? (
            <div style={{color:'var(--text-muted)'}}>No steps recorded.</div>
          ) : (
            <div style={{display:'flex', flexDirection:'column', gap:12}}>
              {steps.map((s:any, i:number) => {
                const expanded = expandedSteps.has(i);
                return (
                  <div key={i} style={{border:`1px solid var(--border)`, borderRadius:'var(--radius-sm)', overflow:'hidden'}}>
                    <div 
                      style={{padding:12, background: expanded ? 'rgba(255,255,255,0.02)' : 'transparent', display:'flex', alignItems:'center', justifyContent:'space-between', cursor:'pointer'}}
                      onClick={() => toggleStep(i)}
                    >
                      <div style={{display:'flex', alignItems:'center', gap:12}}>
                        <div style={{width:24, textAlign:'center', color:'var(--text-muted)', fontSize:12}}>{i+1}</div>
                        {s.success ? <CheckCircle size={16} color="var(--success)" /> : <XCircle size={16} color="var(--danger)" />}
                        <span style={{fontFamily:'monospace', color:'var(--text)', fontSize:14}}>{s.tool_name}</span>
                        <div style={{display:'flex', gap:6, color:'var(--text-muted)'}}>
                          {s.reasoning && <span title="Has reasoning"><MessageSquare size={14} /></span>}
                          {s.tool_output != null && <span title="Has output"><Code size={14} /></span>}
                        </div>
                      </div>
                      <div style={{fontSize:12, color:'var(--text-muted)'}}>{fmtLatency(s.latency_ms)}</div>
                    </div>
                    {expanded && (
                      <div style={{padding:16, borderTop:'1px solid var(--border)', fontSize:13, background:'rgba(0,0,0,0.2)'}}>
                        {!s.success && (
                          <div style={{marginBottom:16}}>
                            <Link href={`/recall?q=${encodeURIComponent(episode.task)}&outcome=success`} className="btn btn-ghost" style={{display:'inline-flex', alignItems:'center', gap:6, padding:'6px 12px', border:'1px solid var(--border)', color:'var(--text)'}}>
                              <SearchCode size={14} /> Find successful episode for this task
                            </Link>
                          </div>
                        )}
                        {s.reasoning && (
                          <div style={{marginBottom:12}}>
                            <div style={{color:'var(--text-muted)', marginBottom:4, fontWeight:500}}>Reasoning</div>
                            <div style={{color:'var(--text)', whiteSpace:'pre-wrap'}}>{s.reasoning}</div>
                          </div>
                        )}
                        {s.tool_input != null && (
                          <div style={{marginBottom:12}}>
                            <div style={{color:'var(--text-muted)', marginBottom:4, fontWeight:500}}>Input</div>
                            <pre style={{margin:0, padding:8, background:'rgba(255,255,255,0.05)', borderRadius:4, overflowX:'auto', color:'var(--accent)'}}>
                              {JSON.stringify(s.tool_input, null, 2)}
                            </pre>
                          </div>
                        )}
                        {s.tool_output != null && (
                          <div>
                            <div style={{color:'var(--text-muted)', marginBottom:4, fontWeight:500}}>Output</div>
                            <pre style={{margin:0, padding:8, background:'rgba(255,255,255,0.05)', borderRadius:4, overflowX:'auto'}}>
                              {JSON.stringify(s.tool_output, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ScoreMetric({ name, val, desc }: { name: string; val?: number; desc: string }) {
  if (val == null) return null;
  return (
    <div>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', fontSize:13}}>
        <span style={{color:'var(--text)'}}>{name}</span>
        <span style={{fontWeight:600, color: scoreColor(val)}}>{Math.round(val * 100)}%</span>
      </div>
      <div style={{fontSize:11, color:'var(--text-muted)', marginTop:2}}>{desc}</div>
    </div>
  );
}
