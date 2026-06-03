"use client";

import React, { useState, useEffect } from "react";
import { Key, Loader2, Plus, Copy, Trash2, X, LogOut, Check } from "lucide-react";
import { keysApi } from "@/lib/api-client";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import { useRouter } from "next/navigation";

interface KeyRow {
  id: string;
  label: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export default function SettingsPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string>("");
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [loadingKeys, setLoadingKeys] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (supabaseConfigured) {
      getSupabase().auth.getUser().then(({ data }) => setEmail(data.user?.email || ""));
    }
    fetchKeys();
  }, []);

  const fetchKeys = async () => {
    setLoadingKeys(true);
    try {
      const data = await keysApi.getKeys();
      setKeys(data.keys || []);
    } catch (err) {
      console.error("Failed to fetch keys", err);
    } finally {
      setLoadingKeys(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const data = await keysApi.createKey(newLabel.trim() || "default");
      setGeneratedKey(data.api_key);
      fetchKeys();
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to create key.");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    if (!confirm("Revoke this key? Agents using it will stop recording immediately.")) return;
    try {
      await keysApi.revokeKey(id);
      setKeys((ks) => ks.filter((k) => k.id !== id));
    } catch {
      alert("Failed to revoke key.");
    }
  };

  const copyKey = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const closeModal = () => {
    setModalOpen(false);
    setGeneratedKey(null);
    setNewLabel("");
    setError("");
  };

  const handleSignOut = async () => {
    if (supabaseConfigured) await getSupabase().auth.signOut();
    router.replace("/login");
  };

  return (
    <div className="p-8 relative">
      {/* Generate-key modal */}
      {modalOpen && (
        <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-zinc-200 w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between bg-zinc-50/50">
              <h2 className="font-semibold text-zinc-900">{generatedKey ? "Your new API key" : "Create API key"}</h2>
              <button onClick={closeModal} className="text-zinc-400 hover:text-zinc-600"><X size={18} /></button>
            </div>

            {!generatedKey ? (
              <form onSubmit={handleCreate} className="p-6 space-y-4">
                <p className="text-sm text-zinc-500">
                  This key lets your agents record episodes under your account. Paste it into the AGeval SDK.
                </p>
                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">Label</label>
                  <input
                    type="text" autoFocus value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    placeholder="e.g. production agents, CI runner"
                    className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                  />
                </div>
                {error && <div className="rounded-md bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</div>}
                <div className="pt-2 flex justify-end gap-3">
                  <button type="button" onClick={closeModal} className="h-9 px-4 rounded-md text-sm font-medium text-zinc-600 hover:bg-zinc-100">Cancel</button>
                  <button type="submit" disabled={creating} className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 disabled:opacity-60">
                    {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create
                  </button>
                </div>
              </form>
            ) : (
              <div className="p-6 space-y-4">
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-amber-800 mb-1">Copy this key now.</h3>
                  <p className="text-xs text-amber-700">You won&apos;t be able to see it again after closing.</p>
                </div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-zinc-100 border border-zinc-200 rounded-md p-2 text-sm text-zinc-800 font-mono break-all">{generatedKey}</code>
                  <button onClick={() => copyKey(generatedKey)} className="h-10 px-3 rounded-md border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-600">
                    {copied ? <Check size={16} className="text-emerald-600" /> : <Copy size={16} />}
                  </button>
                </div>
                <div className="rounded-md bg-zinc-50 border border-zinc-200 p-3">
                  <div className="text-xs text-zinc-500 mb-1">Use it in your agent:</div>
                  <pre className="text-xs font-mono text-zinc-700 overflow-x-auto">{`export AGEVAL_API_KEY="${generatedKey}"
# then in your code:
import ageval.auto   # one line — records every tool call`}</pre>
                </div>
                <div className="pt-2 flex justify-end">
                  <button onClick={closeModal} className="h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800">Done</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="max-w-4xl mx-auto space-y-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Settings & API Keys</h1>
            <p className="text-zinc-500 mt-1 text-sm">
              {email ? <>Signed in as <span className="font-medium text-zinc-700">{email}</span>.</> : "Manage your API keys."}
            </p>
          </div>
          <button onClick={handleSignOut} className="flex items-center gap-2 h-9 px-3 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:bg-zinc-50">
            <LogOut size={14} /> Sign out
          </button>
        </div>

        {/* API keys */}
        <section className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-zinc-200 bg-zinc-50/50 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key size={18} className="text-zinc-500" />
              <h2 className="font-medium text-zinc-900">API Keys</h2>
            </div>
            <button onClick={() => setModalOpen(true)} className="flex items-center gap-2 h-8 px-3 rounded-md bg-zinc-900 text-white text-xs font-medium hover:bg-zinc-800">
              <Plus size={14} /> Create key
            </button>
          </div>

          {loadingKeys ? (
            <div className="flex items-center justify-center h-32 text-zinc-400"><Loader2 className="animate-spin" size={20} /></div>
          ) : keys.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-zinc-400">
              No API keys yet. Create one to start recording your agents&apos; runs.
            </div>
          ) : (
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/50 border-b border-zinc-100">
                <tr>
                  <th className="px-6 py-3 font-medium">Label</th>
                  <th className="px-6 py-3 font-medium">Key</th>
                  <th className="px-6 py-3 font-medium">Last used</th>
                  <th className="px-6 py-3 font-medium">Created</th>
                  <th className="px-6 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {keys.map((k) => (
                  <tr key={k.id} className="hover:bg-zinc-50">
                    <td className="px-6 py-3 font-medium text-zinc-900">{k.label || "Untitled"}</td>
                    <td className="px-6 py-3 font-mono text-zinc-400 text-xs">ageval-sk-••••</td>
                    <td className="px-6 py-3 text-zinc-500">{k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : "never"}</td>
                    <td className="px-6 py-3 text-zinc-500">{k.created_at ? new Date(k.created_at).toLocaleDateString() : "—"}</td>
                    <td className="px-6 py-3 text-right">
                      <button onClick={() => handleRevoke(k.id)} className="text-rose-500 hover:text-rose-700 p-1" title="Revoke key">
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <p className="text-xs text-zinc-400">
          Keys authenticate your <span className="font-medium text-zinc-600">agents</span> (the SDK). You authenticate the
          dashboard with your email &amp; password — no key needed here.
        </p>
      </div>
    </div>
  );
}
