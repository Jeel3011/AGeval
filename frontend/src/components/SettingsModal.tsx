'use client';
import { useState, useEffect } from 'react';
import { apiGet, getConfig } from '@/lib/api';
import { useToast } from './Toast';

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const [key, setKey] = useState('');
  const [url, setUrl] = useState('');
  const [remember, setRemember] = useState(false);
  const [testing, setTesting] = useState(false);
  const [userInfo, setUserInfo] = useState<string | null>(null);

  useEffect(() => {
    const cfg = getConfig();
    setKey(cfg.key);
    setUrl(cfg.base);
    setRemember(!!localStorage.getItem('ageval_key'));
  }, []);

  const handleTestAndSave = async () => {
    setTesting(true);
    try {
      // Test basic connection
      await fetch(`${url}/health`);
      
      // Test auth
      const res = await fetch(`${url}/episodes?limit=1`, {
        headers: { Authorization: `Bearer ${key}` }
      });
      if (!res.ok) throw new Error('Invalid API Key');
      
      const storage = remember ? localStorage : sessionStorage;
      const other = remember ? sessionStorage : localStorage;
      
      storage.setItem('ageval_key', key);
      storage.setItem('ageval_url', url);
      other.removeItem('ageval_key');
      other.removeItem('ageval_url');
      
      setUserInfo('Connection successful');
      toast('Connected securely', 'success');
      setTimeout(onClose, 1000);
    } catch (err: any) {
      toast(`Connection failed: ${err.message}`, 'error');
    } finally {
      setTesting(false);
    }
  };

  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal" style={{position:'fixed', top:'50%', left:'50%', transform:'translate(-50%, -50%)', zIndex: 1000}}>
        <div className="modal-header">
          <h2 style={{margin:0, fontSize:18}}>Settings</h2>
          <button style={{background:'none',border:'none',color:'var(--text)',cursor:'pointer',fontSize:18}} onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div style={{marginBottom: 16}}>
            <label style={{display:'block', marginBottom:8, fontSize:14, fontWeight:500}}>API Key</label>
            <input className="input" type="password" value={key} onChange={e => setKey(e.target.value)} placeholder="ageval-sk-..." />
            <label style={{display:'flex', alignItems:'center', gap:8, marginTop:8, fontSize:12, color:'var(--text-muted)'}}>
              <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
              Remember key in this browser (localStorage)
            </label>
          </div>
          <div style={{marginBottom: 16}}>
            <label style={{display:'block', marginBottom:8, fontSize:14, fontWeight:500}}>API Base URL</label>
            <input className="input" value={url} onChange={e => setUrl(e.target.value)} />
          </div>
          {userInfo && (
            <div style={{padding:16, background:'rgba(34,197,94,0.1)', border:'1px solid var(--success)', borderRadius:'var(--radius-sm)', color:'var(--success)', marginTop:16}}>
              {userInfo}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleTestAndSave} disabled={testing}>
            {testing ? 'Testing...' : 'Test & Connect'}
          </button>
        </div>
      </div>
    </>
  );
}
