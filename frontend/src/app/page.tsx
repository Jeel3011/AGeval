"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Reveal } from "@/components/ui/Reveal";
import { FLEET_VERTICALS, FLEET_TOTAL, WORKFLOWS } from "@/lib/fleet-data";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Boxes,
  Brain,
  CheckCircle2,
  Database,
  Gauge,
  GitBranch,
  Layers,
  Radio,
  Route,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  Workflow,
  Zap,
} from "lucide-react";

/* ────────────────────────────────────────────────────────────────────────
   The hero's live demo is the WEDGE: an agent runs, and AGeval renders a
   verdict on each step *as it happens* — allow / warn / escalate — against the
   agent's evaluation memory, so the agent can act before bad output ships.
   This mirrors the real /live-eval page and POST /evaluate(/stream).
   Canned + real-shaped so the hero always works with no backend.
   ──────────────────────────────────────────────────────────────────────── */
type Action = "allow" | "warn" | "escalate";
type LiveStep = {
  i: number;
  tool: string;
  action: Action;
  reason: string;
};

// A real-shaped trajectory: a credit-analyst agent that wanders off its golden
// path, gets a live "warn", and is caught before it acts on a stale figure.
const LIVE_STEPS: LiveStep[] = [
  { i: 0, tool: "sec_company_facts", action: "allow", reason: "on the golden path" },
  { i: 1, tool: "world_bank_indicator", action: "allow", reason: "on the golden path" },
  { i: 2, tool: "crossref_works", action: "warn", reason: "off the golden path (prefix adherence 0.00)" },
  { i: 3, tool: "process_payment", action: "escalate", reason: "matches known failure · charge before verify" },
];

const ACTION_META: Record<Action, { cls: string; dot: string; icon: any; label: string }> = {
  allow: { cls: "text-emerald-600 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500", icon: ShieldCheck, label: "allow" },
  warn: { cls: "text-amber-600 bg-amber-50 border-amber-200", dot: "bg-amber-500", icon: AlertTriangle, label: "warn" },
  escalate: { cls: "text-orange-600 bg-orange-50 border-orange-200", dot: "bg-orange-500", icon: ShieldAlert, label: "escalate" },
};

/* The four-layer evaluation memory that makes the verdict trustworthy. */
const MEMORY_LAYERS = [
  { icon: ShieldAlert, name: "Failure signatures", note: "Clusters failures into named signatures and tracks recurrence — so a repeat of a known mistake is caught the instant it reappears." },
  { icon: Activity, name: "Peer baselines", note: "Every score and tool input placed against the distribution of runs like it — a 100× outlier charge is flagged, not averaged away." },
  { icon: Route, name: "Golden paths", note: "Mines the ideal tool sequence per task cluster, then warns the moment a run wanders off it — catches wrong-path, right-answer." },
  { icon: TrendingDown, name: "Drift & regression", note: "Diffs an agent's recent runs against its baseline — score deltas, new failures, and new trajectory shapes, version over version." },
];

/* The frameworks / surfaces the real fleet proves out. */
const FRAMEWORKS = [
  { icon: Workflow, name: "LangGraph", note: "StateGraph · ReAct · human-in-the-loop" },
  { icon: Boxes, name: "CrewAI", note: "multi-agent crews" },
  { icon: GitBranch, name: "AutoGen", note: "group chat" },
  { icon: Layers, name: "MCP", note: "tools served over Model Context Protocol" },
  { icon: Zap, name: "OpenAI", note: "function calling" },
  { icon: Activity, name: "Anthropic", note: "Claude tool use" },
];

const STATS = [
  { value: "142", label: "real agents on live APIs" },
  { value: "20", label: "industry verticals" },
  { value: "20", label: "multi-step workflows" },
  { value: "28", label: "built-in metrics" },
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

function ActionPill({ action }: { action: Action }) {
  const m = ACTION_META[action];
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium ${m.cls}`}>
      <Icon className="h-3 w-3" /> {m.label}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   The hero's live verdict console — "watch the eval think". Steps stream in;
   each gets a verdict the instant it appears; the run is caught at escalate.
   ──────────────────────────────────────────────────────────────────────── */
function LiveVerdictConsole() {
  const [shown, setShown] = useState(0);
  const [caught, setCaught] = useState(false);

  const reset = () => { setShown(0); setCaught(false); };

  useInterval(() => {
    if (shown < LIVE_STEPS.length) {
      const next = shown + 1;
      setShown(next);
      if (LIVE_STEPS[next - 1]?.action === "escalate") setCaught(true);
    }
  }, caught ? null : 1100);

  useEffect(() => {
    if (shown < LIVE_STEPS.length) return;
    const t = setTimeout(reset, 4200);
    return () => clearTimeout(t);
  }, [shown]);

  const running = shown < LIVE_STEPS.length && !caught;

  return (
    <div className="glass rounded-2xl p-1.5 ag-float">
      {/* window chrome */}
      <div className="flex items-center justify-between px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
          <span className="ml-2 text-[11px] font-medium text-zinc-500 tracking-wide">
            live eval · credit_analyst_v1
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-zinc-500">
          <Radio className={`h-3 w-3 ${running ? "text-emerald-500 dot-live" : caught ? "text-orange-500" : "text-zinc-400"}`} />
          {caught ? "caught mid-run" : running ? "evaluating each step" : "complete"}
        </div>
      </div>

      {/* recessed screen */}
      <div className="well rounded-xl p-3.5">
        <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-zinc-400 px-1 mb-2">
          <span>Verdict stream</span>
          <span>{shown}/{LIVE_STEPS.length} steps</span>
        </div>
        <div className="space-y-1.5 min-h-[210px]">
          {LIVE_STEPS.slice(0, shown).map((s) => (
            <div key={s.i} className="ag-step-in flex items-start gap-2.5 rounded-lg bg-white/70 border border-white px-3 py-2">
              <span className={`mt-1 h-2 w-2 rounded-full shrink-0 ${ACTION_META[s.action].dot}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <code className="text-[12px] font-semibold text-zinc-900">{s.tool}</code>
                  <ActionPill action={s.action} />
                </div>
                <p className="text-[11px] text-zinc-500 leading-snug">{s.reason}</p>
              </div>
            </div>
          ))}
          {shown === 0 && (
            <div className="text-[12px] text-zinc-400 px-1 py-10 text-center">agent starting…</div>
          )}
        </div>

        {/* the punchline: the agent acts on the verdict */}
        <div className={`mt-3 rounded-lg p-3 flex items-center justify-between transition-colors ${caught ? "glass-dark text-white" : "bg-white/60 border border-white text-zinc-500"}`}>
          <div>
            <div className="text-[10px] uppercase tracking-wider opacity-60">Policy action</div>
            <div className="text-sm font-semibold">
              {caught ? "blocked before execution — routed to review" : running ? "watching…" : "clean run"}
            </div>
          </div>
          <Gauge className={`h-5 w-5 ${caught ? "text-white/70" : "text-zinc-400"}`} />
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Fleet showcase — an animated grid of all 142 agents (one dot each), grouped
   by vertical, rippling "alive" to convey live traffic. Real counts.
   ──────────────────────────────────────────────────────────────────────── */
function FleetShowcase() {
  const [active, setActive] = useState(0);
  useInterval(() => setActive((n) => (n + 1) % FLEET_VERTICALS.length), 2200);

  return (
    <div className="glass rounded-2xl p-5 md:p-6">
      <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr] items-center">
        {/* left: the live grid of 142 agents */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] uppercase tracking-wider text-zinc-400">The fleet · {FLEET_TOTAL} agents</span>
            <span className="flex items-center gap-1.5 text-[11px] text-zinc-500">
              <Radio className="h-3 w-3 text-emerald-500 dot-live" /> live on real APIs
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {FLEET_VERTICALS.flatMap((v, vi) =>
              Array.from({ length: v.count }).map((_, ai) => {
                const idx = vi * 10 + ai;
                const inActive = vi === active;
                return (
                  <span
                    key={`${vi}-${ai}`}
                    className={`ag-tile-live h-3.5 w-3.5 rounded-[4px] border transition-all duration-300 ${inActive ? "border-zinc-900 scale-125 bg-zinc-900" : "border-white"}`}
                    style={{ ["--d" as any]: `${idx * 40}ms` }}
                    title={v.label}
                  />
                );
              })
            )}
          </div>
        </div>

        {/* right: the vertical legend, the active one highlighted */}
        <div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {FLEET_VERTICALS.map((v, i) => (
              <div
                key={v.label}
                className={`flex items-center justify-between text-[12px] py-0.5 px-2 rounded-md transition-colors ${i === active ? "bg-zinc-900 text-white" : "text-zinc-600"}`}
              >
                <span className="truncate">{v.label}</span>
                <span className="tabular-nums opacity-70 ml-2">{v.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Workflows showcase — the 20 elaborate multi-stage workflows. One is
   "playing" at a time: its stages light up left→right with a travelling dot.
   ──────────────────────────────────────────────────────────────────────── */
const STAGE_LABEL: Record<string, string> = {
  synth: "synthesize", post_slack: "slack", post_webhook: "webhook", db_write: "db write",
  make_qr: "qr", short_link: "short link",
};
function stageLabel(s: string) { return STAGE_LABEL[s] || s.replace(/_/g, " "); }
function isAction(s: string) { return ["post_slack", "post_webhook", "db_write", "make_qr", "short_link"].includes(s); }

function WorkflowsShowcase() {
  const [playing, setPlaying] = useState(0);
  useInterval(() => setPlaying((n) => (n + 1) % WORKFLOWS.length), 2600);

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {WORKFLOWS.map((w, i) => {
        const live = i === playing;
        return (
          <div
            key={w.title}
            className={`glass ed-tile rounded-xl p-4 transition-all ${live ? "ring-2 ring-zinc-900" : ""}`}
          >
            <div className="flex items-center justify-between mb-2.5">
              <div className="min-w-0">
                <div className="font-medium text-sm text-zinc-900 truncate">{w.title}</div>
                <div className="text-[11px] text-zinc-400">{w.vertical} · {w.stages.length} stages</div>
              </div>
              {live && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-600 shrink-0">
                  <Radio className="h-3 w-3 dot-live" /> running
                </span>
              )}
            </div>
            {/* the pipeline: stages + a travelling dot when live */}
            <div className="relative flex items-center gap-1 flex-wrap">
              {w.stages.map((st, si) => (
                <React.Fragment key={si}>
                  <span
                    className={`${live ? "ag-stage-in" : ""} rounded-md px-1.5 py-0.5 text-[10px] font-mono border ${
                      st === "synth"
                        ? "bg-zinc-900 text-white border-zinc-900"
                        : isAction(st)
                        ? "bg-amber-50 text-amber-700 border-amber-200"
                        : "bg-white/70 text-zinc-600 border-white"
                    }`}
                    style={{ ["--d" as any]: `${si * 160}ms` }}
                  >
                    {stageLabel(st)}
                  </span>
                  {si < w.stages.length - 1 && <span className="text-zinc-300 text-[10px]">→</span>}
                </React.Fragment>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Landing() {
  const [progress, setProgress] = useState(0);
  const [scrollY, setScrollY] = useState(0);

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
    <div className="ag-canvas min-h-screen text-zinc-900" style={{ ["--sy" as any]: scrollY }}>
      {/* scroll-progress bar */}
      <div
        className="fixed left-0 top-0 z-50 h-0.5 bg-zinc-900 origin-left transition-transform duration-75"
        style={{ width: "100%", transform: `scaleX(${progress})` }}
        aria-hidden
      />
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
            <a href="#wedge" className="hover:text-zinc-900 transition">The wedge</a>
            <a href="#memory" className="hover:text-zinc-900 transition">Memory</a>
            <a href="#fleet" className="hover:text-zinc-900 transition">Real fleet</a>
            <a href="#workflows" className="hover:text-zinc-900 transition">Workflows</a>
          </div>
          <Link href="/login" className="skeu-ghost rounded-lg px-3.5 py-1.5 text-sm font-medium">
            Sign in
          </Link>
        </nav>
      </header>

      {/* Hero — split: pitch left, live verdict console right */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 pt-8 pb-10 md:pt-14">
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_1fr]">
          {/* left: pitch */}
          <div>
            <Reveal as="div" delay={0} className="inline-flex items-center gap-2 rounded-full glass px-3 py-1 text-[12px] text-zinc-600 mb-6">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 dot-live" />
              In-the-loop evaluation · render a verdict mid-run
            </Reveal>
            <Reveal as="h1" delay={80} className="ed-display text-[2.6rem] leading-[1.05] md:text-[3.6rem] text-zinc-900">
              The autopilot for AI agents.
              <br className="hidden md:block" />
              <span className="text-zinc-400">Not a flight recorder.</span>
            </Reveal>
            <Reveal as="p" delay={160} className="mt-5 text-base md:text-lg text-zinc-500 leading-relaxed max-w-xl">
              Every other eval tool watches your agent <em>after</em> it runs. AGeval judges
              each step <em>as</em> it runs — against four layers of evaluation memory — and
              hands back a trustworthy verdict the agent can act on: warn, escalate, or block
              before bad output ever reaches a user.
            </Reveal>
            <Reveal as="div" delay={240} className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/login" className="skeu rounded-xl px-5 py-2.5 text-sm font-medium text-white flex items-center gap-2">
                <Gauge className="h-4 w-4" /> Open the dashboard
              </Link>
              <a href="#wedge" className="skeu-ghost rounded-xl px-5 py-2.5 text-sm font-medium flex items-center gap-2">
                See how it works <ArrowRight className="h-4 w-4" />
              </a>
            </Reveal>
            <Reveal as="p" delay={320} className="mt-4 text-[12px] text-zinc-400">
              One line to integrate · <code className="font-mono">session.evaluate_step()</code> for the verdict,{" "}
              <code className="font-mono">import ageval.auto</code> for zero-code capture
            </Reveal>
          </div>

          {/* right: live verdict console */}
          <div id="demo" className="ed-parallax scroll-mt-24">
            <Reveal variant="scale" delay={120}>
              <LiveVerdictConsole />
            </Reveal>
            <p className="mt-3 text-center text-[12px] text-zinc-400">
              A real-shaped run — each step scored against memory the instant it happens.
            </p>
          </div>
        </div>

        {/* stat strip */}
        <Reveal as="div" delay={200} className="mt-14 grid grid-cols-2 md:grid-cols-4 gap-3">
          {STATS.map((s) => (
            <div key={s.label} className="glass rounded-xl px-4 py-4 text-center">
              <div className="ed-display text-2xl md:text-3xl text-zinc-900 tabular-nums">{s.value}</div>
              <div className="text-[12px] text-zinc-500 mt-1 leading-tight">{s.label}</div>
            </div>
          ))}
        </Reveal>
      </section>

      {/* The wedge — retrospective vs in-the-loop */}
      <section id="wedge" className="relative z-10 mx-auto max-w-6xl px-6 py-16 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">The wedge</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            Stop reading post-mortems. Act mid-run.
          </h2>
          <p className="mt-3 text-zinc-500 max-w-2xl mx-auto">
            LangSmith, Langfuse, Braintrust and Arize all do the same thing: observe, ingest,
            score later. By the time you see the number, the bad output already shipped.
          </p>
        </Reveal>
        <div className="grid gap-4 md:grid-cols-2">
          <Reveal variant="left">
            <div className="glass rounded-2xl p-6 h-full">
              <div className="text-[11px] uppercase tracking-wider text-zinc-400 mb-2">Everyone else — flight recorder</div>
              <h3 className="text-lg font-semibold tracking-tight">Observe → ingest → score later</h3>
              <p className="mt-2 text-sm text-zinc-500 leading-relaxed">
                You learn a run was bad after it finished. The dashboard is an autopsy: useful for
                debugging, useless for stopping the failure that already happened.
              </p>
              <div className="mt-4 flex items-center gap-2 text-[12px] text-zinc-400 font-mono">
                run → finish → <span className="text-zinc-300">…minutes later…</span> → score
              </div>
            </div>
          </Reveal>
          <Reveal delay={120}>
            <div className="glass-dark text-white rounded-2xl p-6 h-full">
              <div className="text-[11px] uppercase tracking-wider text-white/50 mb-2">AGeval — autopilot</div>
              <h3 className="text-lg font-semibold tracking-tight">Judge each step → act before it ships</h3>
              <p className="mt-2 text-sm text-white/70 leading-relaxed">
                A no-LLM, in-process verdict on every step against the agent&apos;s memory. The agent
                gets <code className="font-mono">allow / warn / escalate / block</code> in
                milliseconds — and can repair, route to review, or stop before output reaches a user.
              </p>
              <div className="mt-4 flex items-center gap-2 text-[12px] text-white/60 font-mono">
                step → <span className="text-emerald-400">verdict</span> → act → step → …
              </div>
            </div>
          </Reveal>
        </div>
        <Reveal delay={160} className="mt-4 text-center text-[12px] text-zinc-400">
          Shadow-first by default — verdicts are advisory until you opt a policy into enforce mode. It can only ever make actions <em>stricter</em>, never looser.
        </Reveal>
      </section>

      {/* Evaluation memory */}
      <section id="memory" className="relative z-10 mx-auto max-w-6xl px-6 pb-4 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">Why the verdict is trustworthy</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            Four layers of evaluation memory
          </h2>
          <p className="mt-3 text-zinc-500 max-w-2xl mx-auto">
            The verdict isn&apos;t a guess — it&apos;s scored against everything the agent has done
            before. The more it runs, the sharper the verdict gets.
          </p>
        </Reveal>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {MEMORY_LAYERS.map((f, i) => (
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

      {/* Real fleet */}
      <section id="fleet" className="relative z-10 mx-auto max-w-6xl px-6 py-16 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">Proven on real traffic</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            142 real agents. 20 industries. Live APIs.
          </h2>
          <p className="mt-3 text-zinc-500 max-w-2xl mx-auto">
            Not toy demos. A fleet of real business agents — credit analysts pulling SEC EDGAR
            10-Ks, pharmacovigilance bots scanning openFDA recalls, logistics planners hitting
            live transit data — plus 20 elaborate multi-step workflows, all scored end-to-end.
          </p>
        </Reveal>

        {/* animated fleet grid */}
        <Reveal variant="scale" className="mb-12">
          <FleetShowcase />
        </Reveal>

        {/* frameworks the fleet proves out */}
        <Reveal className="text-center mb-6">
          <div className="ed-kicker mb-2">Across every framework</div>
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

      {/* Workflows showcase */}
      <section id="workflows" className="relative z-10 mx-auto max-w-6xl px-6 pb-16 scroll-mt-20">
        <Reveal className="text-center mb-10">
          <div className="ed-kicker mb-3">Beyond single calls</div>
          <h2 className="ed-display text-2xl md:text-4xl text-zinc-900">
            20 elaborate, multi-stage workflows
          </h2>
          <p className="mt-3 text-zinc-500 max-w-2xl mx-auto">
            Real business processes — several live tool stages that feed each other, an LLM
            synthesis, and sometimes a real side-effect action. Each run is a ≥4-step trajectory
            scored against the golden path. Watch one play through its pipeline.
          </p>
        </Reveal>
        <Reveal variant="scale">
          <WorkflowsShowcase />
        </Reveal>
      </section>

      {/* Metrics + integration */}
      <section id="integrate" className="relative z-10 mx-auto max-w-6xl px-6 pb-16 scroll-mt-20">
        <div className="grid gap-5 lg:grid-cols-2">
          <Reveal as="div" variant="left" className="glass rounded-2xl p-6">
            <ShieldCheck className="h-6 w-6 text-zinc-700" />
            <h3 className="mt-3 text-lg font-semibold tracking-tight">28 built-in metrics + your own</h3>
            <p className="mt-2 text-sm text-zinc-500 leading-relaxed">
              Deterministic reliability and efficiency metrics, three independent scorers (rules,
              LLM judge, custom), error classification, backtracking and token economy — computed
              on every episode, and ranked by what dragged the score so you see <em>why</em>.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {["tool_call_precision", "goal_progress", "reasoning_action_alignment", "backtrack_rate",
                "token_economy", "error_recovery_speed", "golden_path_adherence"].map((m) => (
                <span key={m} className="rounded-md bg-white/70 border border-white px-2 py-1 text-[11px] font-mono text-zinc-600">
                  {m}
                </span>
              ))}
            </div>
          </Reveal>

          <Reveal as="div" delay={120} className="glass rounded-2xl p-6">
            <Database className="h-6 w-6 text-zinc-700" />
            <h3 className="mt-3 text-lg font-semibold tracking-tight">Integrate in one line</h3>
            <p className="mt-2 text-sm text-zinc-500">Wrap your loop for tracing, or ask for a verdict mid-run.</p>
            <pre className="mt-4 well rounded-xl p-4 text-[12px] leading-relaxed font-mono text-zinc-700 overflow-x-auto">
{`from ageval import AgentSession

s = AgentSession(agent_id="credit_v1")

# ask BEFORE you run a step
v = s.evaluate_step("process_payment",
                    {"amount": 4200})
if v.action == "escalate":
    route_to_human(v.explain())   # caught`}
            </pre>
          </Reveal>
        </div>

        <Reveal as="div" variant="scale" className="mt-10 glass-dark rounded-2xl p-8 text-center text-white">
          <Brain className="h-7 w-7 mx-auto text-white/70" />
          <h3 className="mt-3 ed-display text-2xl md:text-3xl">
            Give your agents an autopilot.
          </h3>
          <p className="mt-2 text-white/60 text-sm max-w-xl mx-auto">
            Drop in one call, run your agent, and watch each step get a live verdict — then see
            the provenance behind every score in the dashboard.
          </p>
          <Link href="/login" className="mt-6 inline-flex items-center gap-2 skeu-ghost rounded-xl px-5 py-2.5 text-sm font-medium text-zinc-900">
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
