"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  // Auth guard: a signed-in Supabase session (or a manually stored key for
  // power users) is required to view the dashboard. Otherwise → /login.
  useEffect(() => {
    let active = true;
    const check = async () => {
      const hasStoredKey =
        typeof window !== "undefined" && !!localStorage.getItem("ageval_key");
      if (!supabaseConfigured) {
        // Auth not configured — fall back to stored-key gating only.
        if (active) {
          if (!hasStoredKey) router.replace("/login");
          else setChecked(true);
        }
        return;
      }
      const { data } = await getSupabase().auth.getSession();
      if (!active) return;
      if (data.session || hasStoredKey) {
        setChecked(true);
      } else {
        router.replace("/login");
      }
    };
    check();

    // React to sign-out elsewhere.
    if (supabaseConfigured) {
      const { data: sub } = getSupabase().auth.onAuthStateChange((_e, session) => {
        if (!session && !localStorage.getItem("ageval_key")) router.replace("/login");
      });
      return () => { active = false; sub.subscription.unsubscribe(); };
    }
    return () => { active = false; };
  }, [router]);

  if (!checked) {
    return (
      <div className="flex h-screen w-full items-center justify-center text-zinc-400">
        <Loader2 className="animate-spin" size={24} />
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full text-zinc-900 selection:bg-zinc-200 overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Header />
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
