'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Activity, Layers, Network, ActivitySquare, Database, Settings } from 'lucide-react';
import { useEffect, useState } from 'react';
import { SettingsModal } from './SettingsModal';

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const links = [
    { href: '/', label: 'Health', icon: Activity },
    { href: '/episodes', label: 'Episodes', icon: Layers },
    { href: '/clusters', label: 'Clusters', icon: Network },
    { href: '/compare', label: 'Compare', icon: ActivitySquare },
    { href: '/recall', label: 'Recall', icon: Database },
  ];

  useEffect(() => {
    let keyBuffer = '';
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      
      if (e.key === 'Escape') setSettingsOpen(false);
      
      if (e.key === 'g') {
        const nextFn = (ev: KeyboardEvent) => {
          if (ev.key === 'h') router.push('/');
          if (ev.key === 'e') router.push('/episodes');
          if (ev.key === 'c') router.push('/clusters');
          if (ev.key === 'v') router.push('/compare');
          if (ev.key === 'r') router.push('/recall');
          document.removeEventListener('keydown', nextFn);
        };
        document.addEventListener('keydown', nextFn);
        setTimeout(() => document.removeEventListener('keydown', nextFn), 1000);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [router]);

  return (
    <aside className="sidebar">
      <div className="brand">
        <Activity color="var(--accent)" /> AGeval <span style={{fontSize:12, color:'var(--text-muted)'}}>v0.4 (Next.js)</span>
      </div>
      
      <nav style={{flex: 1}}>
        {links.map(l => {
          const Icon = l.icon;
          const isActive = pathname === l.href;
          return (
            <Link key={l.href} href={l.href} className={`nav-link ${isActive ? 'active' : ''}`}>
              <Icon size={18} /> {l.label}
            </Link>
          );
        })}
      </nav>

      <div style={{ marginTop: 'auto', paddingTop: 24, borderTop: '1px solid var(--border)' }}>
        <button className="btn btn-ghost" style={{width:'100%', display:'flex', gap:8, alignItems:'center', justifyContent:'center'}} onClick={() => setSettingsOpen(true)}>
          <Settings size={16} /> Settings
        </button>
      </div>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </aside>
  );
}
