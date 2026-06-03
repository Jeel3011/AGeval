"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Reveal } from "@/components/ui/Reveal";
import {
  Activity,
  ArrowRight,
  Boxes,
  Brain,
  CheckCircle2,
  Database,
  GitBranch,
  Layers,
  Play,
  Route,
  RotateCcw,
  ShieldCheck,
  TrendingDown,
  Workflow,
  Zap,
} from "lucide-react";

/* ────────────────────────────────────────────────────────────────────────
   Live demo data — a real-shaped scored episode (the e-commerce order agent
   from examples/agents/02). Canned so the hero demo always works with no
   backend, but identical in shape to what AGeval records and scores.
   ──────────────────────────────────────────────────────────────────────── */
type Step = {
  i: number;
  tool: string;
  reasoning: string;
  ok: boolean;
  ms: number;
  out: string;
};

const DEMO_STEPS: Step[] = [
  { i: 0, tool: "get_product", reasoning: "Verify the SKU and its price before ordering", ok: true, ms: 18, out: "Green Cap · $14.00" },
  { i: 1, tool: "check_inventory", reasoning: "Confirm there is enough stock for 2 units", ok: true, ms: 12, out: "in_stock: 37" },
  { i: 2, tool: "create_order", reasoning: "Place the order now that stock is confirmed", ok: true, ms: 41, out: "ORD-8e9a9687 · total $28.00" },
  { i: 3, tool: "process_payment", reasoning: "Charge the buyer the order total", ok: true, ms: 96, out: "ch_4f1c… captured" },
  { i: 4, tool: "send_email", reasoning: "Email the buyer their receipt", ok: true, ms: 27, out: "msg_b21a… queued" },
];

const DEMO_METRICS: { label: string; value: number }[] = [
  { label: "Tool-call precision", value: 1.0 },
  { label: "Goal progress", value: 0.96 },
  { label: "Reasoning ↔ action", value: 0.94 },
  { label: "Token economy", value: 0.88 },
  { label: "Step economy", value: 0.91 },
];

const SCORERS = [
  { name: "Rules", score: 0.97 },
  { name: "LLM Judge", score: 0.93 },
  { name: "Custom", score: 0.9 },
];

/* Evaluation-memory signals — what AGeval remembers across runs and uses to
   make each new score smarter. Real-shaped, canned for the public demo. */
const MEMORY = {
  // §1.2 peer-relative scoring: this run vs its task cluster's baseline.
  relative: { percentile: 92, band: "top 10% of runs like it", n: 64 },
  // §1.3 trajectory adherence: how closely the path matched the golden one.
  adherence: { score: 1.0, golden: ["get_product", "check_inventory", "create_order", "process_payment", "send_email"] },
  // §1.4 failure-pattern triage: nearest known failure signature (not hit here).
  failure: { matched: false, nearest: "env_error · process_payment · late", recurrence: 0 },
  // §2.1 regression vs the previous version of this agent.
  regression: { scorer: "custom", delta: +0.04, newFailures: 0, status: "stable" },
};

/* The frameworks / surfaces the example fleet proves out. */
const FRAMEWORKS = [
  { icon: Workflow, name: "LangGraph", note: "StateGraph · ReAct · human-in-the-loop" },
  { icon: Boxes, name: "CrewAI", note: "multi-agent crews" },
  { icon: GitBranch, name: "AutoGen", note: "group chat" },
  { icon: Layers, name: "MCP", note: "tools served over Model Context Protocol" },
  { icon: Zap, name: "OpenAI", note: "function calling" },
  { icon: Activity, name: "Anthropic", note: "Claude tool use" },
];

function useInterval(cb: () => void, delay: number | null) {
  const saved = useRef(cb);
  useEffect(() => { saved.current = cb; });
  useEffect(() => {
    if (delay === null) return;
    const id = setInterval(() => saved.current(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

/* ────────────────────────────────────────────────────────────────────────
   The animated "scored episode replay" — the hero's live demo.
   ──────────────────────────────────────────────────────────────────────── */
function LiveDemo() {
  const [shown, setShown] = useState(0);      // how many steps revealed
  const [scoring, setScoring] = useState(false);
  const [done, setDone] = useState(false);

  const reset = () => { setShown(0); setScoring(false); setDone(false); };

  // Stream steps in, then run "scoring", then show the scorecard.
  useInterval(() => {
    if (shown < DEMO_STEPS.length) {
      setShown((n) => n + 1);
    } else if (!scoring && !done) {
      setScoring(true);
      setTimeout(() => { setScoring(false); setDone(true); }, 1100);
    }
  }, done ? null : 850);

  // Auto-loop a few seconds after completion.
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(reset, 5200);
    return () => clearTimeout(t);
  }, [done]);

  const totalMs = DEMO_STEPS.slice(0, shown).reduce((a, s) => a + s.ms, 0);

  return (
    <div className="glass rounded-2xl p-1.5 ag-float">
      {/* Title bar — skeuomorphic window chrome */}
      <div className="flex items-center justify-between px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="ml-2 text-[11px] font-medium text-zinc-500 tracking-wide">
            episode · ecommerce_order_v1
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-zinc-500">
          <span className="h-2 w-2 rounded-full bg-zinc-800 dot-live" />
          {done ? "scored" : scoring ? "scoring…" : "running"}
        </div>
      </div>

      {/* Recessed "screen" */}
      <div className="well rounded-xl p-3.5 grid gap-3 md:grid-cols-5">
        {/* Steps stream */}
        <div className="md:col-span-3 space-y-1.5">
          <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-zinc-400 px-1">
            <span>Trace</span>
            <span>{totalMs}ms · {shown}/{DEMO_STEPS.length} steps</span>
          </div>
          {DEMO_STEPS.slice(0, shown).map((s) => (
            <div
              key={s.i}
              className="ag-step-in flex items-start gap-2.5 rounded-lg bg-white/70 border border-white px-3 py-2"
            >
              <div className="mt-0.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-zinc-700" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <code className="text-[12px] font-semibold text-zinc-900">{s.tool}</code>
                  <span className="text-[10px] text-zinc-400">{s.ms}ms</span>
                </div>
                <p className="text-[11px] text-zinc-500 leading-snug truncate">{s.reasoning}</p>
                <p className="text-[11px] text-zinc-700 font-mono truncate">→ {s.out}</p>
              </div>
            </div>
          ))}
          {shown === 0 && (
            <div className="text-[12px] text-zinc-400 px-1 py-6 text-center">starting agent…</div>
          )}
        </div>

        {/* Scorecard */}
        <div className="md:col-span-2 space-y-3">
          <div className="rounded-lg bg-white/70 border border-white p-3">
            <div className="text-[11px] uppercase tracking-wider text-zinc-400 mb-2">Scores</div>
            {SCORERS.map((sc) => (
              <div key={sc.name} className="flex items-center justify-between py-0.5">
                <span className="text-[12px] text-zinc-600">{sc.name}</span>
                <span className="text-[12px] font-semibold text-zinc-900 tabular-nums">
                  {done ? sc.score.toFixed(2) : "—"}
                </span>
              </div>
            ))}
          </div>

          <div className="rounded-lg bg-white/70 border border-white p-3">
            <div className="text-[11px] uppercase tracking-wider text-zinc-400 mb-2">
              Metric breakdown
            </div>
            <div className="space-y-2">
              {DEMO_METRICS.map((m, idx) => (
                <div key={m.label}>
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 mb-0.5">
                    <span className="truncate">{m.label}</span>
                    <span className="tabular-nums text-zinc-700">
                      {done ? m.value.toFixed(2) : "·"}
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-zinc-200/70 overflow-hidden">
                    {done && (
                      <div
                        className="ag-bar h-full rounded-full bg-zinc-800"
                        style={{ width: `${m.value * 100}%`, animationDelay: `${idx * 80}ms` }}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg glass-dark text-white p-3 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-white/50">Outcome</div>
              <div className="text-sm font-semibold">{done ? "success" : "evaluating"}</div>
            </div>
            <button
              onClick={reset}
              className="flex items-center gap-1.5 text-[11px] text-white/70 hover:text-white transition"
            >
              <RotateCcw className="h-3 w-3" /> replay
            </button>
          </div>
        </div>

        {/* Evaluation memory — what AGeval remembers to make this score smarter */}
        <div className="md:col-span-5 mt-1">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-zinc-400 px-1 mb-1.5">
            <Brain className="h-3 w-3" /> Evaluation memory
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {/* Peer-relative score */}
            <MemoryCard
              icon={<Activity className="h-3.5 w-3.5" />}
              label="Peer-relative"
              ready={done}
            >
              <div className="text-[13px] font-semibold text-zinc-900 tabular-nums">
                {done ? `P${MEMORY.relative.percentile}` : "—"}
              </div>
              <div className="text-[10px] text-zinc-500 leading-tight">
                {done ? MEMORY.relative.band : "scoring vs cluster"}
              </div>
            </MemoryCard>

            {/* Trajectory adherence */}
            <MemoryCard
              icon={<Route className="h-3.5 w-3.5" />}
              label="Trajectory"
              ready={done}
            >
              <div className="text-[13px] font-semibold text-zinc-900 tabular-nums">
                {done ? MEMORY.adherence.score.toFixed(2) : "—"}
              </div>
              <div className="text-[10px] text-zinc-500 leading-tight">
                {done ? "matched golden path" : "vs golden path"}
              </div>
            </MemoryCard>

            {/* Failure triage */}
            <MemoryCard
              icon={<ShieldCheck className="h-3.5 w-3.5" />}
              label="Failure triage"
              ready={done}
            >
              <div className="text-[13px] font-semibold text-zinc-900">
                {done ? "no known failure" : "—"}
              </div>
              <div className="text-[10px] text-zinc-500 leading-tight truncate" title={MEMORY.failure.nearest}>
                {done ? `nearest: ${MEMORY.failure.nearest}` : "matching signatures"}
              </div>
            </MemoryCard>

            {/* Regression vs previous version */}
            <MemoryCard
              icon={<TrendingDown className="h-3.5 w-3.5" />}
              label="Regression"
              ready={done}
            >
              <div className="text-[13px] font-semibold text-zinc-900 tabular-nums">
                {done ? `${MEMORY.regression.delta >= 0 ? "+" : ""}${MEMORY.regression.delta.toFixed(2)}` : "—"}
              </div>
              <div className="text-[10px] text-zinc-500 leading-tight">
                {done ? `${MEMORY.regression.status} vs prev version` : "vs previous version"}
              </div>
            </MemoryCard>
          </div>
        </div>
      </div>
    </div>
  );
}

function MemoryCard({
  icon, label, ready, children,
}: { icon: React.ReactNode; label: string; ready: boolean; children: React.ReactNode }) {
  return (
    <div className={`rounded-lg bg-white/70 border border-white p-2.5 transition-opacity ${ready ? "opacity-100" : "opacity-50"}`}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-400 mb-1">
        <span className="text-zinc-500">{icon}</span> {label}
      </div>
      {children}
    </div>
  );
}

export default function Landing() {
  const [progress, setProgress] = useState(0);
  const [scrollY, setScrollY] = useState(0);

  // Scroll progress bar + a single shared scroll offset that drives subtle
  // parallax on hero accents (via the --sy CSS var). rAF-throttled.
  useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        const h = document.documentElement;
        const max = h.scrollHeight - h.clientHeight;
        setProgress(max > 0 ? h.scrollTop / max : 0);
        setScrollY(h.scrollTop);
        raf = 0;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      className="ag-canvas min-h-screen text-zinc-900"
      style={{ ["--sy" as any]: scrollY }}
    >
      {/* scroll-progress bar */}
      <div
        className="fixed left-0 top-0 z-50 h-0.5 bg-zinc-900 origin-left transition-transform duration-75"
        style={{ width: "100%", transform: `scaleX(${progress})` }}
        aria-hidden
      />
      {/* faint grid behind everything */}
      <div className="pointer-events-none fixed inset-0 ag-grid" aria-hidden />

      {/* Nav */}
      <header className="relative z-10">
        <nav className="mx-auto max-w-6xl flex items-center justify-between px-6 py-5">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg skeu flex items-center justify-center">
              <Activity className="h-4 w-4 text-white" />
            </div>
            <span className="font-semibold tracking-tight">AGeval</span>
          </div>
          <div className="hidden md:flex items-center gap-7 text-sm text-zinc-500">
            <a href="#demo" className="hover:text-zinc-900 transition">Live demo</a>
            <a href="#frameworks" className="hover:text-zinc-900 transition">Frameworks</a>
            <a href="#memory" className="hover:text-zinc-900 transition">Memory</a>
            <a href="#metrics" className="hover:text-zinc-900 transition">Metrics</a>
          </div>
          <Link
            href="/login"
            className="skeu-ghost rounded-lg px-3.5 py-1.5 text-sm font-medium"
          >
            Sign in
          </Link>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 pt-10 pb-6 md:pt-16">
        <div className="mx-auto max-w-3xl text-center">
          <Reveal as="div" delay={0} className="inline-flex items-center gap-2 rounded-full glass px-3 py-1 text-[12px] text-zinc-600 mb-6">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-800 dot-live" />
            Evaluation for real agents — 17 reference agents across 6 frameworks
          </Reveal>
          <Reveal as="h1" delay={80} className="ed-display text-[2.75rem] md:text-[4rem] text-zinc-900">
            Observability &amp; scoring for
            <br className="hidden md:block" /> production LLM agents.
          </Reveal>
          <Reveal as="p" delay={160} className="mt-5 text-base md:text-lg text-zinc-500 leading-relaxed max-w-2xl mx-auto">
            AGeval records every tool call your agent makes — across LangGraph, CrewAI,
            AutoGen, MCP, OpenAI and Anthropic — and turns each run into a scored episode.
            Its evaluation memory then scores every run against runs like it, the golden
            path, and the previous version — so scoring gets smarter over time.
          </Reveal>
          <Reveal as="div" delay={240} className="mt-8 flex items-center justify-center gap-3">
            <a
              href="#demo"
              className="skeu rounded-xl px-5 py-2.5 text-sm font-medium text-white flex items-center gap-2"
            >
              <Play className="h-4 w-4" /> Watch a scored run
            </a>
            <Link
              href="/login"
              className="skeu-ghost rounded-xl px-5 py-2.5 text-sm font-medium flex items-center gap-2"
            >
              Open dashboard <ArrowRight className="h-4 w-4" />
            </Link>
          </Reveal>
          <Reveal as="p" delay={320} className="mt-4 text-[12px] text-zinc-400">
            One function call to integrate · <code className="font-mono">trace_openai()</code>,{" "}
            <code className="font-mono">trace_anthropic()</code>,{" "}
            <code className="font-mono">AgentSession()</code>
          </Reveal>
        </div>

        {/* Live demo — drifts subtly with scroll for depth */}
        <div id="demo" className="mt-12 md:mt-16 scroll-mt-24 ed-parallax">
          <Reveal variant="scale" delay={120}>
            <LiveDemo />
          </Reveal>
          <p className="mt-3 text-center text-[12px] text-zinc-400">
            Live replay of a recorded episode — the same trace + scorecard you get in the dashboard.
          </p>
        </div>
      </section>

      {/* Frameworks */}
      <section id="frameworks" className="relative z-10 mx-auto max-w-6xl px-6 py-16 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">Coverage</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            Works with the agents you actually ship
          </h2>
          <p className="mt-3 text-zinc-500">
            Not toy demos — a fleet of 17 reference agents with real tools, MCP servers and multi-agent crews.
          </p>
        </Reveal>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {FRAMEWORKS.map((f, i) => (
            <Reveal key={f.name} delay={i * 70} variant="scale">
              <div
                className="glass ed-tile rounded-xl p-4 flex items-center gap-3.5"
                onMouseMove={(e) => {
                  const r = e.currentTarget.getBoundingClientRect();
                  e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
                  e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
                }}
              >
                <div className="h-10 w-10 rounded-lg skeu-ghost flex items-center justify-center shrink-0">
                  <f.icon className="h-5 w-5 text-zinc-700" />
                </div>
                <div>
                  <div className="font-medium text-sm">{f.name}</div>
                  <div className="text-[12px] text-zinc-500">{f.note}</div>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Evaluation memory */}
      <section id="memory" className="relative z-10 mx-auto max-w-6xl px-6 pb-4 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">The moat</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            Evaluation memory — scoring that compounds
          </h2>
          <p className="mt-3 text-zinc-500 max-w-2xl mx-auto">
            AGeval doesn&apos;t just score a run in isolation. It remembers every episode and
            uses four memory layers to judge each new run in context.
          </p>
        </Reveal>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { icon: Activity, name: "Peer-relative scoring", note: "Each score placed against the distribution of runs like it — “bottom 10% of runs like it”, not a bare 0.79." },
            { icon: Route, name: "Trajectory adherence", note: "Mines the golden path per task cluster, then scores how closely a run follows it — catches wrong-path, right-answer." },
            { icon: ShieldCheck, name: "Failure-pattern memory", note: "Clusters failures into named signatures, tracks recurrence, and turns each into a regression test in one click." },
            { icon: TrendingDown, name: "Regression detection", note: "Diffs an agent’s recent runs against its baseline — score deltas, new failures, and new trajectory shapes." },
          ].map((f, i) => (
            <Reveal key={f.name} delay={i * 90}>
              <div className="glass ed-tile rounded-xl p-4 h-full">
                <div className="h-10 w-10 rounded-lg skeu-ghost flex items-center justify-center mb-3">
                  <f.icon className="h-5 w-5 text-zinc-700" />
                </div>
                <div className="font-medium text-sm">{f.name}</div>
                <div className="text-[12px] text-zinc-500 mt-1 leading-snug">{f.note}</div>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Metrics + integration */}
      <section id="metrics" className="relative z-10 mx-auto max-w-6xl px-6 pb-16 pt-12 scroll-mt-20">
        <div className="grid gap-5 lg:grid-cols-2">
          <Reveal as="div" variant="left" className="glass rounded-2xl p-6">
            <ShieldCheck className="h-6 w-6 text-zinc-700" />
            <h3 className="mt-3 text-lg font-semibold tracking-tight">19 built-in metrics + your own</h3>
            <p className="mt-2 text-sm text-zinc-500 leading-relaxed">
              Deterministic reliability and efficiency metrics, three scorers (rules,
              LLM judge, custom), error classification, backtracking and token economy —
              computed on every episode automatically.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {["agent_error_rate", "tool_call_precision", "goal_progress", "backtrack_rate",
                "token_economy", "reasoning_action_alignment", "error_recovery_speed"].map((m) => (
                <span key={m} className="rounded-md bg-white/70 border border-white px-2 py-1 text-[11px] font-mono text-zinc-600">
                  {m}
                </span>
              ))}
            </div>
          </Reveal>

          <Reveal as="div" delay={120} className="glass rounded-2xl p-6">
            <Database className="h-6 w-6 text-zinc-700" />
            <h3 className="mt-3 text-lg font-semibold tracking-tight">Integrate in one line</h3>
            <p className="mt-2 text-sm text-zinc-500">Wrap your existing loop — no rewrite.</p>
            <pre className="mt-4 well rounded-xl p-4 text-[12px] leading-relaxed font-mono text-zinc-700 overflow-x-auto">
{`from ageval import trace_anthropic

result = trace_anthropic(
    client, messages, tools, tool_functions,
    agent_id="support_v1",
    task="resolve the SLA refund",
)
# → result["episode_id"] is now scored`}
            </pre>
          </Reveal>
        </div>

        <Reveal as="div" variant="scale" className="mt-10 glass-dark rounded-2xl p-8 text-center text-white">
          <h3 className="ed-display text-2xl md:text-3xl">
            See your own agents scored.
          </h3>
          <p className="mt-2 text-white/60 text-sm max-w-xl mx-auto">
            Drop in one function call, run your agent, and watch the episode and its
            scorecard appear in the dashboard.
          </p>
          <Link
            href="/login"
            className="mt-6 inline-flex items-center gap-2 skeu-ghost rounded-xl px-5 py-2.5 text-sm font-medium text-zinc-900"
          >
            Open the dashboard <ArrowRight className="h-4 w-4" />
          </Link>
        </Reveal>
      </section>

      <footer className="relative z-10 mx-auto max-w-6xl px-6 py-8 text-[12px] text-zinc-400 flex items-center justify-between">
        <span>© {new Date().getFullYear()} AGeval</span>
        <span className="font-mono">v0.3.0</span>
      </footer>
    </div>
  );
}
