"use client";

import React, { useEffect, useState } from "react";
import { Sparkles, Loader2, Mail, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

type Mode = "signin" | "signup";

/** Turn raw Supabase auth errors into clear, actionable copy. */
function friendlyAuthError(err: unknown, mode: Mode): string {
  const raw = (err instanceof Error ? err.message : String(err ?? "")).toLowerCase();
  if (raw.includes("rate limit")) {
    return "Too many requests in a short window. Wait a minute and try again.";
  }
  if (raw.includes("already registered") || raw.includes("already been registered") || raw.includes("user already exists")) {
    return "An account with this email already exists. Switch to Sign in instead.";
  }
  if (raw.includes("invalid login credentials")) {
    return "Incorrect email or password.";
  }
  if (raw.includes("password should be") || raw.includes("password")) {
    return "Password must be at least 6 characters.";
  }
  return err instanceof Error ? err.message : `${mode === "signup" ? "Sign-up" : "Sign-in"} failed.`;
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Already signed in? Go straight to the dashboard.
  useEffect(() => {
    if (!supabaseConfigured) return;
    getSupabase().auth.getSession().then(({ data }) => {
      if (data.session) router.replace("/dashboard");
    });
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");

    if (!supabaseConfigured) {
      setError("Auth is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.");
      return;
    }
    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }

    setBusy(true);
    try {
      const supabase = getSupabase();
      if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({ email: email.trim(), password });
        if (error) throw error;
        // With "Confirm email" disabled in Supabase, sign-up returns a session
        // immediately and we go straight to the dashboard. Keep a fallback
        // notice in case confirmation ever gets re-enabled.
        if (!data.session) {
          setNotice("Account created — please sign in.");
          setMode("signin");
          return;
        }
        router.replace("/dashboard");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (error) throw error;
        router.replace("/dashboard");
      }
    } catch (err: unknown) {
      setError(friendlyAuthError(err, mode));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-50 py-12 px-4">
      <div className="max-w-md w-full space-y-8">
        <div className="flex flex-col items-center">
          <div className="w-12 h-12 rounded-xl bg-zinc-900 flex items-center justify-center mb-4">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h2 className="text-3xl font-semibold tracking-tight text-zinc-900">
            {mode === "signup" ? "Create your AGeval account" : "Sign in to AGeval"}
          </h2>
          <p className="mt-2 text-sm text-zinc-500">
            {mode === "signup"
              ? "Start scoring your agents in minutes."
              : "Welcome back. Sign in to your dashboard."}
          </p>
        </div>

        {/* Tabs */}
        <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-zinc-100">
          {(["signin", "signup"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { setMode(m); setError(""); setNotice(""); }}
              className={`h-9 rounded-md text-sm font-medium transition-colors ${
                mode === m ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-900"
              }`}
            >
              {m === "signin" ? "Sign in" : "Sign up"}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1">Email</label>
            <div className="relative">
              <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                type="email" required autoFocus autoComplete="email"
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="w-full h-10 rounded-md border border-zinc-300 bg-white pl-9 pr-3 text-sm text-zinc-900 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1">Password</label>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                type="password" required
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "signup" ? "At least 6 characters" : "••••••••"}
                className="w-full h-10 rounded-md border border-zinc-300 bg-white pl-9 pr-3 text-sm text-zinc-900 outline-none focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-rose-50 border border-rose-200 px-4 py-3 text-sm text-rose-700">{error}</div>
          )}
          {notice && (
            <div className="rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">{notice}</div>
          )}

          <button type="submit" disabled={busy}
            className="w-full flex justify-center items-center gap-2 h-10 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors disabled:opacity-60">
            {busy ? <><Loader2 size={16} className="animate-spin" /> {mode === "signup" ? "Creating account…" : "Signing in…"}</>
              : (mode === "signup" ? "Create account" : "Sign in")}
          </button>
        </form>

        <p className="text-center text-xs text-zinc-400">
          {mode === "signin" ? (
            <>New to AGeval? <button onClick={() => setMode("signup")} className="underline hover:text-zinc-700">Create an account</button></>
          ) : (
            <>Already have an account? <button onClick={() => setMode("signin")} className="underline hover:text-zinc-700">Sign in</button></>
          )}
        </p>
        <p className="text-center text-xs text-zinc-400">
          After signing in, generate an API key in <span className="font-medium text-zinc-600">Settings → API Keys</span> and drop it into your agent.
        </p>
      </div>
    </div>
  );
}
