"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  CheckCircle2,
  Database,
  LayoutDashboard,
  Settings,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
  Users
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
        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2">Platform</div>
        <NavItem href="/" icon={<LayoutDashboard size={18} />} label="Dashboard" active={pathname === "/"} />
        <NavItem href="/traces" icon={<Activity size={18} />} label="Traces & Logs" active={pathname.startsWith("/traces")} />
        <NavItem href="/datasets" icon={<Database size={18} />} label="Golden Datasets" active={pathname.startsWith("/datasets")} />
        <NavItem href="/playground" icon={<TerminalSquare size={18} />} label="Playground" active={pathname.startsWith("/playground")} />
        
        <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-2 mt-6">Evaluation</div>
        <NavItem href="/test-suites" icon={<CheckCircle2 size={18} />} label="Test Suites" active={pathname.startsWith("/test-suites")} />
        <NavItem href="/red-teaming" icon={<ShieldAlert size={18} />} label="Red Teaming" active={pathname.startsWith("/red-teaming")} />
        
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
