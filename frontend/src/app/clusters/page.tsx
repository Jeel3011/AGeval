'use client';
import { useEffect, useState } from 'react';
import { apiGet } from '@/lib/api';
import { useToast } from '@/components/Toast';
import { scoreColor } from '@/lib/utils';
import Link from 'next/link';
import { Network } from 'lucide-react';

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
    <div>
      <header style={{marginBottom: 32}}>
        <h1 style={{margin:0, fontSize:24, fontWeight:600}}>Task Clusters</h1>
        <p style={{margin:0, color:'var(--text-muted)'}}>Automatically grouped recurring task patterns.</p>
      </header>

      {loading ? (
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:24}}>
           <div className="skeleton" style={{height: 200}} />
           <div className="skeleton" style={{height: 200}} />
        </div>
      ) : clusters.length === 0 ? (
        <div style={{padding:64, textAlign:'center', color:'var(--text-muted)', border:'1px dashed var(--border)', borderRadius:'var(--radius-md)'}}>
          <Network size={32} style={{opacity:0.5, marginBottom:16}} />
          <div>No clusters found. Agent behavior may not be clustered yet.</div>
        </div>
      ) : (
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:24}}>
          {clusters.map((c, i) => (
            <div key={i} className="card" style={{border: c.drift < -0.1 ? '1px solid var(--danger)' : '1px solid var(--border)'}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:16}}>
                <h3 style={{margin:0, fontSize:18}}>{c.label || `Cluster ${c.id}`}</h3>
                {c.drift < -0.1 && <span className="badge badge-danger">REGRESSING ({Math.round(c.drift * 100)}%)</span>}
              </div>
              <div style={{fontSize:14, color:'var(--text-muted)', marginBottom:24}}>
                {c.episode_count} episodes
              </div>
              
              <div style={{display:'flex', alignItems:'center', gap:12, marginBottom:16}}>
                <div style={{fontSize:24, fontWeight:600, color: scoreColor(c.avg_score)}}>{c.avg_score != null ? `${Math.round(c.avg_score * 100)}%` : 'N/A'}</div>
                <div style={{flex:1, height:6, background:'rgba(255,255,255,0.1)', borderRadius:3, overflow:'hidden'}}>
                  <div style={{height:'100%', width:`${(c.avg_score || 0) * 100}%`, background: scoreColor(c.avg_score)}} />
                </div>
              </div>
              
              <div style={{fontSize:13, color:'var(--text-muted)', marginBottom:24}}>
                Most common failure: <span style={{color:'var(--text)'}}>{c.top_failing_tool || 'unknown'}</span>
              </div>
              
              <div style={{display:'flex', gap:12}}>
                 <Link href={`/episodes?cluster=${c.id}`} className="btn btn-ghost" style={{flex:1, textAlign:'center'}}>View Episodes</Link>
                 <button className="btn btn-ghost" style={{flex:1}} onClick={() => loadFailures(c)}>Failure Detail</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedCluster && (
        <div style={{position:'fixed', top:0, left:0, right:0, bottom:0, background:'rgba(0,0,0,0.8)', display:'flex', alignItems:'center', justifyContent:'center', zIndex:100}}>
          <div className="card" style={{width: 600, maxWidth:'90vw', maxHeight:'80vh', overflowY:'auto'}}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:24}}>
              <h2 style={{margin:0}}>Failures: {selectedCluster.label}</h2>
              <button className="btn-ghost" onClick={() => setSelectedCluster(null)}>Close</button>
            </div>
            
            {failuresLoading ? (
              <div className="skeleton" style={{height:100}} />
            ) : failures.length === 0 ? (
              <div style={{color:'var(--text-muted)'}}>No failing steps recorded in this cluster.</div>
            ) : (
              <div style={{display:'flex', flexDirection:'column', gap:12}}>
                {failures.map((f, i) => (
                  <div key={i} style={{padding:16, border:'1px solid var(--border)', borderRadius:'var(--radius-sm)', background:'rgba(255,255,255,0.02)'}}>
                    <div style={{display:'flex', justifyContent:'space-between', marginBottom:8}}>
                      <span style={{fontFamily:'monospace', fontWeight:600}}>{f.tool_name}</span>
                      <span className="badge badge-danger">{f.count} occurrences</span>
                    </div>
                    <div style={{fontSize:13, color:'var(--text-muted)'}}>
                      Step Index: {f.step_index} | Category: {f.error_category || 'unknown'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
