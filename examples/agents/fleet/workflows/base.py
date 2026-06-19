"""
examples/agents/fleet/workflows/base.py

The elaborate-workflow engine (Phase 2A) + in-eval transparency (Phase 2B).

A `WorkflowSpec` is a real, multi-stage business process — geocode → pull risk
data → score → decide → (gated) write — not a single LLM loop. Each stage calls
a *live* tool and is recorded as an AGeval step, so every workflow run is a
real, multi-step trajectory (≥4 steps) the eval-memory trajectory/golden-path
layers can actually score.

Transparency is built into the same loop: **before** each stage runs we ask
AGeval for a live `Verdict` (`session.evaluate_step`) and, with `explain=True`,
stream it to the console — "watch the eval think". The verdict's rationale
(which layer fired, nearest known failure, z-score vs baseline, golden-path
deviation) is shown live, then the stage runs and is recorded.

Stages can be:
  * a tool stage  — call a real_tools / sideeffects function with args built
    from the accumulating context, OR
  * an llm stage  — a real OpenAI synthesis/decision call over the context.

Both are recorded; the final llm stage produces the workflow's answer.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from examples.agents import real_tools, sideeffects

# Tool name -> (callable, module label) across both real libraries.
_TOOLS: dict[str, tuple[Callable, str]] = {
    **{n: (f, "real_tools") for n, f in real_tools.TOOL_FUNCTIONS.items()},
    **{n: (f, "sideeffects") for n, f in sideeffects.TOOL_FUNCTIONS.items()},
}


@dataclass
class Stage:
    """One step of a workflow.

    For a tool stage set `tool` and `args` (a callable: context -> kwargs dict).
    For an llm stage set `llm_prompt` (a callable: context -> user prompt str).
    """
    name: str
    reasoning: str
    tool: str | None = None
    args: Callable[[dict], dict] | None = None
    llm_prompt: Callable[[dict], str] | None = None
    optional: bool = False        # a failed optional stage doesn't fail the run

    @property
    def kind(self) -> str:
        return "llm" if self.llm_prompt else "tool"


@dataclass
class WorkflowSpec:
    id: str
    vertical: str
    persona: str
    goal: str
    stages: list[Stage]
    framework: str = "pipeline"   # pipeline | langgraph | crewai | autogen
    model: str = ""
    side_effect_stages: list[str] = field(default_factory=list)

    def tool_names(self) -> list[str]:
        return [s.tool for s in self.stages if s.tool]

    def fires_side_effects(self) -> bool:
        return any((s.tool in sideeffects.TOOL_FUNCTIONS) for s in self.stages if s.tool)


@dataclass
class StepTrace:
    """What happened at one stage — recorded AND surfaced for transparency."""
    index: int
    name: str
    kind: str
    verdict_action: str
    verdict_reason: str
    verdict_confidence: float
    success: bool
    summary: str
    latency_ms: int


def _summarize(value: Any, limit: int = 140) -> str:
    try:
        s = json.dumps(value, default=str)
    except Exception:
        s = str(value)
    return s[:limit]


def run_workflow(spec: WorkflowSpec, *, explain: bool = False, client=None,
                 model: str | None = None) -> dict:
    """Run one elaborate workflow live. Returns an episode dict including the
    full per-stage trajectory + the live verdicts (for transparency)."""
    if not os.environ.get("OPENAI_API_KEY"):
        return {}

    from ageval import AgentSession

    chosen = model or spec.model or os.environ.get("AGEVAL_DEMO_OPENAI_MODEL", "gpt-4o-mini")
    if client is None:
        from openai import OpenAI
        client = OpenAI()

    session = AgentSession(agent_id=spec.id, task=spec.goal)
    session.start()

    context: dict[str, Any] = {"goal": spec.goal, "persona": spec.persona}
    traces: list[StepTrace] = []
    final_answer: str | None = None

    if explain:
        print(f"\n┌─ workflow {spec.id}  [{spec.framework}]  {spec.vertical}")
        print(f"│  goal: {spec.goal}")

    for stage in spec.stages:
        # ---- Transparency: ask for a live verdict BEFORE running the stage ----
        proposed_input = {}
        if stage.kind == "tool" and stage.args:
            try:
                proposed_input = stage.args(context)
            except Exception:
                proposed_input = {}
        verdict = session.evaluate_step(
            tool_name=stage.tool or stage.name,
            tool_input=proposed_input,
            reasoning=stage.reasoning,
        )
        if explain:
            conf = f"{verdict.confidence:.2f}"
            print(f"│  ⟳ {stage.name:22s} verdict={verdict.action:8s} conf={conf}  {verdict.explain()}")

        # ---- Run the stage ----
        t0 = time.perf_counter()
        success = True
        try:
            if stage.kind == "llm":
                user_prompt = stage.llm_prompt(context)
                resp = client.chat.completions.create(
                    model=chosen, temperature=0.0,
                    messages=[
                        {"role": "system", "content": f"You are {spec.persona}. Be concise and concrete; "
                                                      f"cite the figures from the context."},
                        {"role": "user", "content": user_prompt},
                    ])
                out = resp.choices[0].message.content
                context[stage.name] = out
                final_answer = out
                latency = int((time.perf_counter() - t0) * 1000)
                session.record_step(tool_name="llm_call", tool_input={"prompt": user_prompt[:500]},
                                    tool_output=out, success=True, reasoning=stage.reasoning,
                                    latency_ms=latency)
            else:
                fn, _mod = _TOOLS[stage.tool]
                kwargs = stage.args(context) if stage.args else {}
                out = fn(**kwargs)
                context[stage.name] = out
                latency = int((time.perf_counter() - t0) * 1000)
                session.record_step(tool_name=stage.tool, tool_input=kwargs, tool_output=out,
                                    success=True, reasoning=stage.reasoning, latency_ms=latency)
        except Exception as exc:
            success = False
            latency = int((time.perf_counter() - t0) * 1000)
            session.record_error(tool_name=stage.tool or stage.name, exc=exc,
                                 reasoning=stage.reasoning, latency_ms=latency)
            context[stage.name] = {"error": f"{type(exc).__name__}: {exc}"}
            if explain:
                print(f"│  ✗ {stage.name:22s} FAILED {type(exc).__name__}: {str(exc)[:80]}")
            if not stage.optional:
                # a required stage failed — record what we have and stop the trajectory
                traces.append(StepTrace(len(traces), stage.name, stage.kind, verdict.action,
                                        verdict.explain(), verdict.confidence, False,
                                        _summarize(context[stage.name]), latency))
                break

        traces.append(StepTrace(len(traces), stage.name, stage.kind, verdict.action,
                                verdict.explain(), verdict.confidence, success,
                                _summarize(context.get(stage.name)), latency))
        if explain and success:
            print(f"│  ✓ {stage.name:22s} {traces[-1].summary}")

    session.finish()
    if explain:
        print(f"└─ episode {session.episode_id}  ({len(traces)} steps)\n")

    return {
        "episode_id": session.episode_id,
        "final_content": final_answer,
        "steps": len(traces),
        "trajectory": [t.__dict__ for t in traces],
        "tools": spec.tool_names(),
        "framework": spec.framework,
        "fired_side_effects": spec.fires_side_effects(),
    }
