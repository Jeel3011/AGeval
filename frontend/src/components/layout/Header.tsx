"use client";

import React, { useState, useRef, useEffect } from "react";
import { ChevronRight, LogOut, User } from "lucide-react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

/** Human label for the current top-level route, for the breadcrumb. */
const ROUTE_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  traces: "Traces & Logs",
  episodes: "Episodes",
  clusters: "Clusters",
  recall: "Semantic Recall",
  compare: "Compare",
  failures: "Failure Memory",
  regression: "Regression",
  datasets: "Golden Datasets",
  "test-suites": "Test Suites",
  "red-teaming": "Red Teaming",
  playground: "Playground",
  team: "Team",
  settings: "Configuration",
};

export function Header() {
  const pathname = usePathname();
  const segment = (pathname || "/dashboard").split("/").filter(Boolean)[0] || "dashboard";
  const crumb = ROUTE_LABELS[segment] || "Dashboard";
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [email, setEmail] = useState<string>("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (supabaseConfigured) {
      getSupabase().auth.getUser().then(({ data }) => setEmail(data.user?.email || ""));
    }
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleLogout = async () => {
    setDropdownOpen(false);
    if (supabaseConfigured) await getSupabase().auth.signOut();
    if (typeof window !== "undefined") localStorage.removeItem("ageval_key");
    router.replace("/login");
  };

  const initials = email ? email.slice(0, 2).toUpperCase() : "AG";

  return (
    <header className="h-16 border-b border-zinc-200 bg-white/80 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-20">
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <Link href="/dashboard" className="hover:text-zinc-900 transition-colors">AGeval</Link>
        <ChevronRight size={14} />
        <span className="font-medium text-zinc-900">{crumb}</span>
      </div>

      <div className="flex items-center gap-4 relative">
        {/* User Dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-8 h-8 rounded-full bg-zinc-100 border border-zinc-200 flex items-center justify-center font-medium text-sm hover:bg-zinc-200 transition-colors focus:outline-none focus:ring-2 focus:ring-zinc-300 focus:ring-offset-1"
          >
            {initials}
          </button>

          {dropdownOpen && (
            <div className="absolute right-0 mt-2 w-56 bg-white border border-zinc-200 rounded-md shadow-lg py-1 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="px-4 py-2 border-b border-zinc-100">
                <p className="text-sm font-medium text-zinc-900">Signed in</p>
                <p className="text-xs text-zinc-500 truncate">{email || "—"}</p>
              </div>
              <div className="p-1">
                <Link href="/settings" className="flex items-center gap-2 px-3 py-1.5 text-sm text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100 rounded-sm transition-colors" onClick={() => setDropdownOpen(false)}>
                  <User size={14} />
                  Profile Settings
                </Link>
                <button 
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-rose-600 hover:text-rose-700 hover:bg-rose-50 rounded-sm transition-colors mt-1"
                >
                  <LogOut size={14} />
                  Log out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
