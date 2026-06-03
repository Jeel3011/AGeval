"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  CheckCircle2,
  Database,
  GitCompare,
  Layers,
  LayoutDashboard,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
  TrendingDown,
  Users,
} from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-zinc-200 bg-white flex flex-col h-screen sticky top-0 shrink-0">
      <div className="h-16 flex items-center px-6 border-b border-zinc-100">
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <div className="w-6 h-6 rounded-md bg-zinc-900 flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="font-semibold text-lg tracking-tight">AGeval</span>
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto py-6 px-4 flex flex-col gap-1">
        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2">Overview</div>
        <NavItem href="/dashboard" icon={<LayoutDashboard size={18} />} label="Dashboard" active={pathname === "/dashboard"} />
        <NavItem href="/traces" icon={<Activity size={18} />} label="Traces & Logs" active={pathname === "/traces"} />

        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2 mt-6">Episodes</div>
        <NavItem href="/episodes" icon={<Layers size={18} />} label="Episodes" active={pathname === "/episodes" || pathname.startsWith("/episodes/")} />
        <NavItem href="/clusters" icon={<GitCompare size={18} />} label="Clusters" active={pathname.startsWith("/clusters")} />
        <NavItem href="/recall" icon={<Search size={18} />} label="Semantic Recall" active={pathname.startsWith("/recall")} />
        <NavItem href="/compare" icon={<GitCompare size={18} />} label="Compare" active={pathname.startsWith("/compare")} />

        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2 mt-6">Memory</div>
        <NavItem href="/failures" icon={<ShieldAlert size={18} />} label="Failure Memory" active={pathname.startsWith("/failures")} />
        <NavItem href="/regression" icon={<TrendingDown size={18} />} label="Regression" active={pathname.startsWith("/regression")} />

        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2 mt-6">Evaluation</div>
        <NavItem href="/datasets" icon={<Database size={18} />} label="Golden Datasets" active={pathname.startsWith("/datasets")} />
        <NavItem href="/test-suites" icon={<CheckCircle2 size={18} />} label="Test Suites" active={pathname.startsWith("/test-suites")} />
        <NavItem href="/red-teaming" icon={<ShieldAlert size={18} />} label="Red Teaming" active={pathname.startsWith("/red-teaming")} />
        <NavItem href="/playground" icon={<TerminalSquare size={18} />} label="Playground" active={pathname.startsWith("/playground")} />

        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2 mt-6">Settings</div>
        <NavItem href="/team" icon={<Users size={18} />} label="Team" active={pathname.startsWith("/team")} />
        <NavItem href="/settings" icon={<Settings size={18} />} label="Configuration" active={pathname.startsWith("/settings")} />
      </div>
    </aside>
  );
}

function NavItem({ href, icon, label, active = false }: { href: string, icon: React.ReactNode, label: string, active?: boolean }) {
  return (
    <Link 
      href={href}
      className={`flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer transition-colors text-sm font-medium ${
        active ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-900'
      }`}
    >
      {icon}
      {label}
    </Link>
  );
}
