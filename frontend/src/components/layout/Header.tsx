"use client";

import React, { useState, useRef, useEffect } from "react";
import { ChevronRight, Search, LogOut, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export function Header() {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

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

  const handleLogout = () => {
    setDropdownOpen(false);
    // Real app would clear tokens here
    router.push("/login");
  };

  return (
    <header className="h-16 border-b border-zinc-200 bg-white/80 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-20">
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <span>Project</span>
        <ChevronRight size={14} />
        <span className="font-medium text-zinc-900">Trip Planner Agent</span>
      </div>
      
      <div className="flex items-center gap-4 relative">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 h-4 w-4 text-zinc-400" />
          <input 
            type="text" 
            placeholder="Search traces..." 
            className="h-8 w-64 rounded-md border border-zinc-200 bg-zinc-50 pl-9 pr-4 text-sm outline-none focus:border-zinc-300 focus:ring-1 focus:ring-zinc-300 transition-all"
          />
        </div>

        {/* User Dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button 
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-8 h-8 rounded-full bg-zinc-100 border border-zinc-200 flex items-center justify-center font-medium text-sm hover:bg-zinc-200 transition-colors focus:outline-none focus:ring-2 focus:ring-zinc-300 focus:ring-offset-1"
          >
            JT
          </button>

          {dropdownOpen && (
            <div className="absolute right-0 mt-2 w-48 bg-white border border-zinc-200 rounded-md shadow-lg py-1 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="px-4 py-2 border-b border-zinc-100">
                <p className="text-sm font-medium text-zinc-900">Jeel Thummar</p>
                <p className="text-xs text-zinc-500 truncate">jeel@example.com</p>
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
