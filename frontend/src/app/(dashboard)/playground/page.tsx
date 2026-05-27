"use client";

import React, { useState } from "react";
import { Play, Settings2, Save, Wand2, Loader2, CheckCircle2 } from "lucide-react";

export default function PlaygroundPage() {
  const [isRunning, setIsRunning] = useState(false);
  const [hasResults, setHasResults] = useState(false);
  const [isSaved, setIsSaved] = useState(false);

  const handleRun = () => {
    setIsRunning(true);
    setHasResults(false);
    setTimeout(() => {
      setIsRunning(false);
      setHasResults(true);
    }, 2000);
  };

  const handleSave = () => {
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 3000);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] relative">
      
      {/* Toast Notification */}
      {isSaved && (
        <div className="fixed bottom-6 right-6 bg-zinc-900 text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-in slide-in-from-bottom-5 fade-in duration-300 z-50">
          <CheckCircle2 size={18} className="text-emerald-400" />
          <span className="text-sm font-medium">Prompt Variant saved successfully.</span>
        </div>
      )}

      {/* Toolbar */}
      <div className="h-14 border-b border-zinc-200 bg-white px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="font-semibold text-zinc-900">Prompt Playground</h1>
          <div className="h-4 w-px bg-zinc-200"></div>
          <select className="h-8 rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm text-zinc-700 outline-none">
            <option>Customer Support Agent - v2</option>
            <option>Customer Support Agent - v1</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button 
            onClick={handleSave}
            className="flex items-center gap-2 h-9 px-4 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-700 hover:bg-zinc-50 transition-colors shadow-sm"
          >
            <Save size={16} />
            Save Variant
          </button>
          <button 
            onClick={handleRun}
            disabled={isRunning}
            className="flex items-center gap-2 h-9 px-4 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors shadow-sm disabled:opacity-70 disabled:cursor-wait"
          >
            {isRunning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            {isRunning ? "Evaluating..." : "Run Test"}
          </button>
        </div>
      </div>

      {/* Main Content Split */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Editor Pane */}
        <div className="w-1/2 border-r border-zinc-200 flex flex-col bg-white">
          <div className="h-10 border-b border-zinc-200 px-4 flex items-center justify-between bg-zinc-50/50">
            <span className="text-xs font-medium text-zinc-500 uppercase tracking-wider">System Prompt</span>
            <button className="text-zinc-400 hover:text-indigo-600 transition-colors"><Wand2 size={14} /></button>
          </div>
          <textarea 
            className="flex-1 p-4 resize-none outline-none text-sm text-zinc-800 font-mono leading-relaxed"
            defaultValue="You are a helpful customer support assistant for Acme Corp. Always answer politely and concisely. If you do not know the answer, say 'I don't know'."
          ></textarea>
          
          <div className="h-10 border-y border-zinc-200 px-4 flex items-center bg-zinc-50/50">
            <span className="text-xs font-medium text-zinc-500 uppercase tracking-wider">Variables</span>
          </div>
          <div className="h-32 p-4 bg-white text-sm font-mono text-zinc-600">
            {"{\n  \"user_query\": \"Where is my order?\"\n}"}
          </div>
        </div>

        {/* Results Pane */}
        <div className="w-1/2 flex flex-col bg-zinc-50">
          <div className="h-10 border-b border-zinc-200 px-4 flex items-center justify-between bg-white">
            <span className="text-xs font-medium text-zinc-500 uppercase tracking-wider">Output & Evaluation</span>
            <button className="text-zinc-400 hover:text-zinc-600"><Settings2 size={14} /></button>
          </div>
          
          <div className="flex-1 p-6 overflow-y-auto">
            {isRunning ? (
              <div className="h-full flex flex-col items-center justify-center text-zinc-400">
                <Loader2 size={32} className="animate-spin mb-4 text-indigo-500" />
                <p className="text-sm font-medium text-zinc-600">Streaming LLM Response...</p>
                <p className="text-xs mt-2">Computing Faithfulness Metrics</p>
              </div>
            ) : hasResults ? (
              <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4">
                <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm">
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Agent Output</h3>
                  <p className="text-sm text-zinc-800 leading-relaxed">
                    I'm sorry, but without an order number I cannot look up your specific order. Please provide your order number and I will be happy to assist you!
                  </p>
                </div>
                
                <div>
                  <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Evaluation Metrics</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm flex items-center justify-between">
                      <span className="text-sm font-medium text-zinc-700">Faithfulness</span>
                      <span className="text-emerald-600 bg-emerald-50 px-2 py-1 rounded text-xs font-bold border border-emerald-100">1.0 (Pass)</span>
                    </div>
                    <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm flex items-center justify-between">
                      <span className="text-sm font-medium text-zinc-700">Answer Relevance</span>
                      <span className="text-emerald-600 bg-emerald-50 px-2 py-1 rounded text-xs font-bold border border-emerald-100">0.95 (Pass)</span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-zinc-400">
                <p className="text-sm">Click "Run Test" to evaluate this prompt variant.</p>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
