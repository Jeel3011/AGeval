"use client";

import React from "react";
import { Filter, Search } from "lucide-react";

export default function TracesPage() {
  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Traces & Logs</h1>
            <p className="text-zinc-500 mt-1 text-sm">View detailed execution paths for all agent runs.</p>
          </div>
        </div>

        <div className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden flex flex-col h-[70vh]">
          {/* Toolbar */}
          <div className="h-14 border-b border-zinc-200 px-4 flex items-center justify-between bg-zinc-50/50">
            <div className="flex items-center gap-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-2 h-4 w-4 text-zinc-400" />
                <input 
                  type="text" 
                  placeholder="Search by Trace ID or task..." 
                  className="h-8 w-72 rounded-md border border-zinc-200 bg-white pl-9 pr-4 text-sm outline-none focus:border-zinc-300 focus:ring-1 focus:ring-zinc-300 transition-all"
                />
              </div>
              <button className="flex items-center gap-2 h-8 px-3 rounded-md border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:text-zinc-900 transition-colors shadow-sm">
                <Filter size={14} />
                Filters
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="flex-1 overflow-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 sticky top-0 border-b border-zinc-200">
                <tr>
                  <th className="px-6 py-3 font-medium">Trace ID</th>
                  <th className="px-6 py-3 font-medium">Task</th>
                  <th className="px-6 py-3 font-medium">Steps</th>
                  <th className="px-6 py-3 font-medium">Score</th>
                  <th className="px-6 py-3 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                <TraceRow id="trc_9a8b7c6d" task="Book flight to CDG" steps={12} score="0.94" time="2 mins ago" />
                <TraceRow id="trc_1f2e3d4c" task="Summarize quarterly report" steps={5} score="0.88" time="15 mins ago" />
                <TraceRow id="trc_5b6n7m8m" task="Process stripe payment" steps={8} score="0.45" time="1 hour ago" failed />
                <TraceRow id="trc_0p9o8i7u" task="Fetch weather for NY" steps={3} score="0.99" time="3 hours ago" />
                <TraceRow id="trc_q1w2e3r4" task="Scrape competitor pricing" steps={24} score="0.72" time="Yesterday" />
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}

function TraceRow({ id, task, steps, score, time, failed = false }: { id: string, task: string, steps: number, score: string, time: string, failed?: boolean }) {
  return (
    <tr className="bg-white hover:bg-zinc-50 transition-colors cursor-pointer group">
      <td className="px-6 py-4 font-mono text-xs text-zinc-500 group-hover:text-zinc-900 transition-colors">
        {id}
      </td>
      <td className="px-6 py-4 font-medium text-zinc-900">
        {task}
      </td>
      <td className="px-6 py-4 text-zinc-600">
        {steps}
      </td>
      <td className="px-6 py-4">
        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${failed ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'}`}>
          {score}
        </span>
      </td>
      <td className="px-6 py-4 text-zinc-500 whitespace-nowrap">
        {time}
      </td>
    </tr>
  );
}
