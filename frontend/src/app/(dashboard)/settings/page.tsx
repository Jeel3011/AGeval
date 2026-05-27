"use client";

import React, { useState, useEffect } from "react";
import { Key, Webhook, Database, Save, Loader2, CheckCircle2, Plus, Copy, Trash2, X } from "lucide-react";
import { keysApi } from "@/lib/api-client";

export default function SettingsPage() {
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [isKeyModalOpen, setIsKeyModalOpen] = useState(false);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [adminSecret, setAdminSecret] = useState("");
  const [isLoadingKeys, setIsLoadingKeys] = useState(true);

  // Load existing keys from backend
  useEffect(() => {
    const fetchKeys = async () => {
      try {
        const data = await keysApi.getKeys();
        if (data.keys) {
          // Format them nicely for UI
          const formatted = data.keys.map((k: any) => ({
            id: k.id,
            label: k.label || "Untitled Key",
            prefix: k.is_active ? "ageval-sk-..." : "Revoked",
            created: new Date(k.created_at).toLocaleDateString()
          }));
          setApiKeys(formatted);
        }
      } catch (err) {
        console.error("Failed to fetch keys", err);
      } finally {
        setIsLoadingKeys(false);
      }
    };
    fetchKeys();
  }, []);

  const handleSave = () => {
    setIsSaving(true);
    setSaved(false);
    setTimeout(() => {
      setIsSaving(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }, 1500);
  };

  const handleGenerateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminSecret) {
      alert("Admin Secret is required to generate a platform API key.");
      return;
    }
    
    try {
      const data = await keysApi.registerKey(newKeyLabel, adminSecret);
      setGeneratedKey(data.api_key);
      
      // Add it to the top of our table visually
      setApiKeys([{
        id: `k_${Date.now()}`,
        label: newKeyLabel || "New Key",
        prefix: data.api_key.substring(0, 15) + "...",
        created: "Just now"
      }, ...apiKeys]);
      
      // Also automatically authenticate the browser with this new key if it's the first one
      if (apiKeys.length === 0) {
        localStorage.setItem("ageval_api_key", data.api_key);
      }
    } catch (err: any) {
      console.error(err);
      alert(err.response?.data?.detail || "Failed to generate key. Check your admin secret.");
    }
  };

  const handleRevoke = async (id: string) => {
    if (!confirm("Are you sure you want to revoke this key? Any agents using it will stop working immediately.")) return;
    try {
      await keysApi.revokeKey(id);
      setApiKeys(apiKeys.filter(key => key.id !== id));
    } catch (err) {
      console.error("Failed to revoke", err);
      alert("Failed to revoke key.");
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="p-8 relative">
      
      {/* Toast Notification */}
      {saved && (
        <div className="fixed bottom-6 right-6 bg-zinc-900 text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-in slide-in-from-bottom-5 fade-in duration-300 z-50">
          <CheckCircle2 size={18} className="text-emerald-400" />
          <span className="text-sm font-medium">Configuration saved successfully.</span>
        </div>
      )}

      {/* Generate Key Modal */}
      {isKeyModalOpen && (
        <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-white rounded-xl shadow-xl border border-zinc-200 w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-zinc-200 flex items-center justify-between bg-zinc-50/50">
              <h2 className="font-semibold text-zinc-900">Generate Platform API Key</h2>
              <button onClick={() => { setIsKeyModalOpen(false); setGeneratedKey(null); setNewKeyLabel(""); }} className="text-zinc-400 hover:text-zinc-600 transition-colors">
                <X size={18} />
              </button>
            </div>
            
            {!generatedKey ? (
              <form onSubmit={handleGenerateKey} className="p-6 space-y-4">
                <p className="text-sm text-zinc-500">This key gives full access to your project's datasets and evaluation engines.</p>
                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">Key Label</label>
                  <input 
                    type="text" 
                    autoFocus
                    required
                    value={newKeyLabel}
                    onChange={(e) => setNewKeyLabel(e.target.value)}
                    placeholder="e.g. Jenkins CI Runner" 
                    className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">Admin Secret</label>
                  <input 
                    type="password" 
                    required
                    value={adminSecret}
                    onChange={(e) => setAdminSecret(e.target.value)}
                    placeholder="Server AGEVAL_ADMIN_SECRET" 
                    className="w-full h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                  />
                </div>
                <div className="pt-2 flex justify-end gap-3">
                  <button type="button" onClick={() => setIsKeyModalOpen(false)} className="h-9 px-4 rounded-md text-sm font-medium text-zinc-600 hover:bg-zinc-100 transition-colors">Cancel</button>
                  <button type="submit" className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors">
                    Generate
                  </button>
                </div>
              </form>
            ) : (
              <div className="p-6 space-y-4">
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-amber-800 mb-1">Please copy this key now.</h3>
                  <p className="text-xs text-amber-700">For security reasons, you will not be able to view it again after closing this window.</p>
                </div>
                <div className="flex items-center gap-2 mt-4">
                  <code className="flex-1 bg-zinc-100 border border-zinc-200 rounded-md p-2 text-sm text-zinc-800 font-mono break-all">
                    {generatedKey}
                  </code>
                  <button onClick={() => handleCopy(generatedKey)} className="h-10 px-3 rounded-md border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-600 transition-colors">
                    <Copy size={16} />
                  </button>
                </div>
                <div className="pt-4 flex justify-end">
                  <button onClick={() => { setIsKeyModalOpen(false); setGeneratedKey(null); setNewKeyLabel(""); }} className="h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors">
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="max-w-4xl mx-auto space-y-8">
        
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Configuration & API Keys</h1>
          <p className="text-zinc-500 mt-1 text-sm">Manage project settings, platform API keys, and external integrations.</p>
        </div>

        <div className="space-y-6">
          {/* Platform API Keys */}
          <section className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200 bg-zinc-50/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Key size={18} className="text-zinc-500" />
                <h2 className="font-medium text-zinc-900">AGeval Platform API Keys</h2>
              </div>
              <button onClick={() => setIsKeyModalOpen(true)} className="flex items-center gap-2 h-8 px-3 rounded-md bg-zinc-900 text-white text-xs font-medium hover:bg-zinc-800 transition-colors">
                <Plus size={14} />
                Generate Key
              </button>
            </div>
            <div className="p-0">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/50 border-b border-zinc-100">
                  <tr>
                    <th className="px-6 py-3 font-medium">Label</th>
                    <th className="px-6 py-3 font-medium">Key Prefix</th>
                    <th className="px-6 py-3 font-medium">Created</th>
                    <th className="px-6 py-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {apiKeys.map(k => (
                    <tr key={k.id} className="hover:bg-zinc-50 transition-colors">
                      <td className="px-6 py-3 font-medium text-zinc-900">{k.label}</td>
                      <td className="px-6 py-3 font-mono text-zinc-500 text-xs">{k.prefix}</td>
                      <td className="px-6 py-3 text-zinc-500">{k.created}</td>
                      <td className="px-6 py-3 text-right">
                        <button 
                          onClick={() => handleRevoke(k.id)}
                          className="text-rose-500 hover:text-rose-700 p-1 transition-colors" title="Revoke Key"
                        >
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* General Settings */}
          <section className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200 bg-zinc-50/50 flex items-center gap-2">
              <Database size={18} className="text-zinc-500" />
              <h2 className="font-medium text-zinc-900">General Settings</h2>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Project Name</label>
                <input 
                  type="text" 
                  defaultValue="Trip Planner Agent" 
                  className="w-full max-w-md h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Project ID</label>
                <input 
                  type="text" 
                  defaultValue="prj_9x8c7v6b" 
                  disabled
                  className="w-full max-w-md h-9 rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm text-zinc-500 outline-none cursor-not-allowed"
                />
              </div>
            </div>
          </section>

          {/* External API Keys */}
          <section className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-zinc-200 bg-zinc-50/50 flex items-center gap-2">
              <Key size={18} className="text-zinc-500" />
              <h2 className="font-medium text-zinc-900">External Provider Keys</h2>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-zinc-500 mb-4">Provide keys for the evaluation engines. These are securely encrypted in our Vault.</p>
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">OpenAI API Key</label>
                <input 
                  type="password" 
                  defaultValue="sk-................................" 
                  className="w-full max-w-md h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none focus:border-zinc-400 focus:ring-1 focus:ring-zinc-400"
                />
              </div>
            </div>
          </section>

          <div className="flex justify-end pt-2 pb-12">
            <button 
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 h-10 px-6 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm disabled:opacity-70 disabled:cursor-wait"
            >
              {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              {isSaving ? "Saving..." : "Save Configuration"}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
