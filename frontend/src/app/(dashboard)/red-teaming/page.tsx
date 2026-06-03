"use client";

import React, { useState } from "react";
import { ShieldAlert, Shield, ShieldCheck, Crosshair, Activity, Loader2 } from "lucide-react";
import { redTeamApi, RedTeamScorecard } from "@/lib/api-client";

const VECTOR_META: Record<string, { title: string; desc: string }> = {
  prompt_injection: {
    title: "Direct Prompt Injection",
    desc: "Attempts to override system instructions via direct user input.",
  },
  roleplay_jailbreak: {
    title: "Roleplay Jailbreaks",
    desc: "Assuming a persona (e.g. DAN) to bypass ethical filters.",
  },
  data_exfiltration: {
    title: "Data Exfiltration",
    desc: "Tricking the agent into leaking its system prompt / secrets.",
  },
  dow: {
    title: "Denial of Wallet (DoW)",
    desc: "Triggering runaway output to rack up LLM API costs.",
  },
};

export default function RedTeamingPage() {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scorecard, setScorecard] = useState<RedTeamScorecard | null>(null);

  const handleRun = async () => {
    setIsRunning(true);
    setError(null);
    try {
      const res = await redTeamApi.run("default_agent");
      setScorecard(res.scorecard);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Red-team run failed");
    } finally {
      setIsRunning(false);
    }
  };

  const grade = scorecard?.overall_grade ?? "—";
  const goodGrade = grade === "A" || grade === "B";

  return (
    <div className="p-8">
      <div className="max-w-6xl mx-auto space-y-8">

        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">Red Teaming</h1>
            <p className="text-zinc-500 mt-1 text-sm">
              Real adversarial probes run against your model via your OpenAI key. Results below are
              derived from the model&apos;s actual responses.
            </p>
          </div>
          <button
            onClick={handleRun}
            disabled={isRunning}
            className="flex items-center gap-2 h-9 px-4 rounded-md bg-rose-600 text-white text-sm font-medium hover:bg-rose-700 transition-colors shadow-sm disabled:opacity-70 disabled:cursor-wait"
          >
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Crosshair size={14} />}
            {isRunning ? "Running probes..." : "Run Attack Simulation"}
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        {!scorecard && !isRunning && !error && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-12 text-center text-sm text-zinc-500 shadow-sm">
            No simulation run yet. Click <span className="font-medium text-zinc-700">Run Attack Simulation</span> to
            probe the model with prompt-injection, jailbreak, data-exfiltration, and denial-of-wallet attacks.
          </div>
        )}

        {scorecard && (
          <>
            {/* Security Score Overview */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="border border-zinc-200 bg-white rounded-xl p-6 shadow-sm flex flex-col items-center justify-center text-center">
                <div className={`w-16 h-16 rounded-full flex items-center justify-center mb-4 border ${goodGrade ? "bg-emerald-50 border-emerald-100 text-emerald-600" : "bg-rose-50 border-rose-100 text-rose-600"}`}>
                  <ShieldAlert size={32} />
                </div>
                <div className="text-4xl font-bold text-zinc-900 tracking-tight">{grade}</div>
                <div className="text-sm font-medium text-zinc-500 mt-1">Security Posture Score</div>
                <div className="text-xs text-zinc-400 mt-2">
                  {scorecard.bypasses}/{scorecard.probes_run} probes bypassed · model {scorecard.model}
                </div>
              </div>

              <div className="col-span-2 border border-zinc-200 bg-white rounded-xl shadow-sm p-6 flex flex-col justify-center">
                <h3 className="font-semibold text-zinc-900 mb-4 flex items-center gap-2">
                  <Activity size={18} className="text-zinc-400" />
                  Bypass Rates by Vector
                </h3>
                <div className="space-y-3">
                  <RateBar label="Prompt Injection" value={scorecard.prompt_injection_bypass_rate} danger />
                  <RateBar label="Roleplay Jailbreak" value={scorecard.roleplay_jailbreak_bypass_rate} danger />
                  <RateBar label="Data Exfiltration" value={scorecard.data_exfiltration_bypass_rate} danger />
                  <RateBar label="Denial of Wallet" value={scorecard.dow_success_rate} />
                </div>
              </div>
            </div>

            {/* Per-probe results */}
            <h3 className="text-lg font-semibold text-zinc-900 mt-8 mb-4">Probe Results</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {scorecard.results.map((r, i) => (
                <ProbeCard key={i} probe={r} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function RateBar({ label, value, danger }: { label: string; value: number; danger?: boolean }) {
  const pct = Math.round(value * 100);
  const color = pct === 0 ? "bg-emerald-500" : danger ? "bg-rose-500" : "bg-amber-500";
  return (
    <div>
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="font-medium text-zinc-700">{label}</span>
        <span className="text-zinc-500">{pct}% bypass</span>
      </div>
      <div className="w-full bg-zinc-100 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all duration-700`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ProbeCard({ probe }: { probe: RedTeamScorecard["results"][number] }) {
  const meta = VECTOR_META[probe.vector] ?? { title: probe.vector, desc: "" };
  const status = probe.bypassed ? "failed" : "passed";
  const icons = {
    passed: <ShieldCheck className="text-emerald-600" size={20} />,
    failed: <ShieldAlert className="text-rose-600" size={20} />,
  };
  const bgs = {
    passed: "bg-emerald-50 border-emerald-100",
    failed: "bg-rose-50 border-rose-100",
  };
  return (
    <div className="border border-zinc-200 bg-white rounded-xl p-5 shadow-sm flex items-start gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border ${bgs[status]}`}>
        {icons[status]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h4 className="font-medium text-zinc-900 truncate">{probe.name}</h4>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded shrink-0 ${probe.bypassed ? "text-rose-600 bg-rose-50" : "text-emerald-600 bg-emerald-50"}`}>
            {probe.bypassed ? "Bypassed" : "Blocked"}
          </span>
        </div>
        <p className="text-sm text-zinc-500 mt-1">{meta.desc}</p>
        {probe.response_preview && (
          <pre className="mt-3 text-xs text-zinc-500 bg-zinc-50 border border-zinc-100 rounded p-2 whitespace-pre-wrap break-words max-h-24 overflow-hidden">
            {probe.response_preview}
          </pre>
        )}
      </div>
    </div>
  );
}
