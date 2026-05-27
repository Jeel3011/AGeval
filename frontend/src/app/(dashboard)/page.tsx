"use client";

import React from "react";
import { ChevronRight } from "lucide-react";

export default function DashboardOverview() {
  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Overview</h1>
            <p className="text-zinc-500 mt-1 text-sm">Agent performance metrics over the last 7 days.</p>
          </div>
          <button className="h-9 px-4 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors shadow-sm">
            Run Evaluation
          </button>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <KpiCard title="Total Traces" value="124,592" change="+12.5%" positive={true} />
          <KpiCard title="Avg. Faithfulness" value="0.94" change="+0.02" positive={true} />
          <KpiCard title="Failure Rate" value="2.4%" change="-0.5%" positive={true} />
          <KpiCard title="Avg. Latency" value="1.2s" change="+0.1s" positive={false} />
        </div>

        {/* Main Chart Area */}
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 border border-zinc-200 bg-white rounded-xl shadow-sm p-6">
            <h3 className="font-semibold text-zinc-900 mb-4">Performance Trends</h3>
            <div className="h-64 w-full bg-zinc-50 rounded-lg border border-zinc-100 flex items-center justify-center text-zinc-400 text-sm">
              [Recharts Interactive Graph Area]
            </div>
          </div>
          <div className="col-span-1 border border-zinc-200 bg-white rounded-xl shadow-sm p-6 flex flex-col">
            <h3 className="font-semibold text-zinc-900 mb-4">Recent Failures</h3>
            <div className="flex-1 flex flex-col gap-3">
              <FailureItem task="Book flight to CDG" error="ToolTimeout" />
              <FailureItem task="Summarize context" error="Hallucination" />
              <FailureItem task="Process payment" error="ValidationError" />
              <FailureItem task="Fetch weather" error="EnvError" />
            </div>
            <button className="mt-4 w-full py-2 text-sm text-zinc-600 font-medium hover:text-zinc-900 hover:bg-zinc-50 rounded-md transition-colors">
              View all failures &rarr;
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

function KpiCard({ title, value, change, positive }: { title: string, value: string, change: string, positive: boolean }) {
  return (
    <div className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm flex flex-col gap-2">
      <div className="text-sm font-medium text-zinc-500">{title}</div>
      <div className="text-2xl font-semibold text-zinc-900 tracking-tight">{value}</div>
      <div className={`text-xs font-medium ${positive ? 'text-emerald-600' : 'text-rose-600'}`}>
        {change} from last week
      </div>
    </div>
  );
}

function FailureItem({ task, error }: { task: string, error: string }) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-zinc-100 bg-zinc-50/50 hover:bg-zinc-50 transition-colors cursor-pointer">
      <div className="flex flex-col gap-0.5 truncate pr-4">
        <span className="text-sm font-medium text-zinc-900 truncate">{task}</span>
        <span className="text-xs text-zinc-500">{error}</span>
      </div>
      <ChevronRight size={14} className="text-zinc-400 shrink-0" />
    </div>
  );
}
