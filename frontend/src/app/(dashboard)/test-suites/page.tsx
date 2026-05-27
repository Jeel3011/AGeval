"use client";

import React from "react";
import { CheckCircle2, Play, Search, Clock, FileText } from "lucide-react";

export default function TestSuitesPage() {
  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Test Suites</h1>
            <p className="text-zinc-500 mt-1 text-sm">Automated evaluation runs against your golden datasets.</p>
          </div>
          <button className="flex items-center gap-2 h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm">
            <Play size={14} className="fill-current" />
            New Run
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <SuiteCard title="Nightly Regression" status="passed" passed={420} failed={0} time="4 hours ago" />
          <SuiteCard title="PR #102 Eval" status="failed" passed={18} failed={2} time="Yesterday" />
          <SuiteCard title="Hallucination Check" status="passed" passed={50} failed={0} time="2 days ago" />
        </div>

        <h3 className="text-lg font-semibold text-zinc-900 mt-8 mb-4">Recent Executions</h3>
        <div className="border border-zinc-200 bg-white rounded-xl shadow-sm overflow-hidden flex flex-col">
          <div className="h-14 border-b border-zinc-200 px-4 flex items-center justify-between bg-zinc-50/50">
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-4 w-4 text-zinc-400" />
              <input 
                type="text" 
                placeholder="Search test runs..." 
                className="h-8 w-72 rounded-md border border-zinc-200 bg-white pl-9 pr-4 text-sm outline-none focus:border-zinc-300 focus:ring-1 focus:ring-zinc-300 transition-all"
              />
            </div>
          </div>
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-zinc-500 uppercase bg-zinc-50/80 border-b border-zinc-200">
              <tr>
                <th className="px-6 py-3 font-medium">Run ID</th>
                <th className="px-6 py-3 font-medium">Suite</th>
                <th className="px-6 py-3 font-medium">Status</th>
                <th className="px-6 py-3 font-medium">Duration</th>
                <th className="px-6 py-3 font-medium">Triggered By</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              <RunRow id="run_4928" suite="Nightly Regression" status="passed" duration="14m 20s" user="system" />
              <RunRow id="run_4927" suite="PR #102 Eval" status="failed" duration="2m 10s" user="jeel@example.com" />
              <RunRow id="run_4926" suite="Adversarial Attack" status="running" duration="In Progress..." user="jeel@example.com" />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SuiteCard({ title, status, passed, failed, time }: { title: string, status: "passed" | "failed", passed: number, failed: number, time: string }) {
  return (
    <div className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${status === 'passed' ? 'bg-emerald-50 border border-emerald-100' : 'bg-rose-50 border border-rose-100'}`}>
            <CheckCircle2 size={16} className={status === 'passed' ? 'text-emerald-600' : 'text-rose-600'} />
          </div>
          <span className="font-semibold text-zinc-900">{title}</span>
        </div>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-1.5 text-zinc-600">
          <FileText size={14} className="text-zinc-400" />
          {passed + failed} tests
        </div>
        <div className="flex items-center gap-1.5 text-zinc-600">
          <Clock size={14} className="text-zinc-400" />
          {time}
        </div>
      </div>
      <div className="flex gap-2 text-xs font-medium mt-auto">
        <span className="text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded">{passed} passed</span>
        {failed > 0 && <span className="text-rose-700 bg-rose-50 border border-rose-100 px-2 py-0.5 rounded">{failed} failed</span>}
      </div>
    </div>
  );
}

function RunRow({ id, suite, status, duration, user }: { id: string, suite: string, status: "passed" | "failed" | "running", duration: string, user: string }) {
  const statusColors = {
    passed: "bg-emerald-100 text-emerald-700",
    failed: "bg-rose-100 text-rose-700",
    running: "bg-amber-100 text-amber-700 animate-pulse"
  };
  
  return (
    <tr className="bg-white hover:bg-zinc-50 transition-colors group cursor-pointer">
      <td className="px-6 py-4 font-mono text-xs text-zinc-500 group-hover:text-zinc-900">
        {id}
      </td>
      <td className="px-6 py-4 font-medium text-zinc-900">
        {suite}
      </td>
      <td className="px-6 py-4">
        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusColors[status]}`}>
          {status.toUpperCase()}
        </span>
      </td>
      <td className="px-6 py-4 text-zinc-500">
        {duration}
      </td>
      <td className="px-6 py-4 text-zinc-500">
        {user}
      </td>
    </tr>
  );
}
