"""
examples/agents/fleet/factory.py

Turns a declarative `AgentSpec` into a *running, real* agent and returns the
AGeval episode dict. "Real" means: a real OpenAI brain drives a tool-calling
loop where every tool performs a live external call (real_tools.py) and,
optionally, a real side effect (sideeffects.py).

The factory is intentionally thin — it just assembles the tool set for a spec
and hands the loop to the existing `trace_openai` tracer, exactly like the
hand-written example agents do. Nothing about a factory-produced agent is
faked: same LLM, same live HTTP, same recording path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from examples.agents import real_tools, sideeffects


@dataclass(frozen=True)
class AgentSpec:
    """A declarative description of one real agent."""
    id: str
    vertical: str
    persona: str
    system_prompt: str
    task: str                       # a real task referencing live data
    tools: list[str]                # names from real_tools / sideeffects
    framework: str = "openai"       # openai | langgraph | crewai | autogen | mcp
    model: str = ""                 # overrides the demo default when set
    max_iterations: int = 6
    side_effect_tools: list[str] = field(default_factory=list)

    def all_tool_names(self) -> list[str]:
        return list(self.tools) + list(self.side_effect_tools)


def _resolve_tools(spec: AgentSpec) -> tuple[list[dict], dict]:
    """Build the OpenAI tool schemas + {name: callable} for a spec, drawing
    from real_tools for reads and sideeffects for writes."""
    read = [t for t in spec.tools if t in real_tools.TOOL_FUNCTIONS]
    side = [t for t in spec.side_effect_tools if t in sideeffects.TOOL_FUNCTIONS]

    unknown = (set(spec.tools) - set(read)) | (set(spec.side_effect_tools) - set(side))
    if unknown:
        raise ValueError(f"spec {spec.id!r} references unknown tools: {sorted(unknown)}")

    # NB: openai_schemas([]) returns ALL tools (empty list is falsy in the
    # shared helper), so only call it when the subset is non-empty.
    schemas = []
    if read:
        schemas += real_tools.openai_schemas(read)
    if side:
        schemas += sideeffects.openai_schemas(side)
    funcs = {**real_tools.subset(read), **sideeffects.subset(side)}
    return schemas, funcs


def build_and_run(spec: AgentSpec, *, model: str | None = None, client=None) -> dict:
    """Run one spec live and return its AGeval episode dict.

    Returns ``{}`` when no OpenAI key is configured (graceful skip, matching the
    example agents' convention).

    When an AGeval API key is configured the run goes through the `trace_openai`
    tracer (full recording + scoring). When it is not — e.g. a read-only sweep
    with recording deliberately off — we still run the *same* real tool loop
    directly, so liveness is proven either way. (The tracer's own no-API
    fall-through makes a single completion with no tools, which wouldn't
    exercise the live APIs; this loop does.)
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return {}

    schemas, funcs = _resolve_tools(spec)
    chosen = model or spec.model or os.environ.get("AGEVAL_DEMO_OPENAI_MODEL", "gpt-4o-mini")
    messages = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": spec.task},
    ]
    if client is None:
        from openai import OpenAI
        client = OpenAI()

    if os.environ.get("AGEVAL_API_KEY"):
        from ageval import trace_openai
        return trace_openai(
            client=client, messages=messages, tools=schemas, tool_functions=funcs,
            agent_id=spec.id, task=spec.task, model=chosen,
            max_iterations=spec.max_iterations, temperature=0.0,
        )

    return _run_loop_unrecorded(client, messages, schemas, funcs, chosen, spec)


def _run_loop_unrecorded(client, messages, schemas, funcs, model, spec) -> dict:
    """A real OpenAI tool-calling loop with no AGeval recording. Mirrors what
    the tracer does (same tools, same live calls) but returns a minimal episode
    dict so the fleet runner can still report liveness + which tools fired."""
    import json

    tool_calls_made: list[str] = []
    for _ in range(spec.max_iterations):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=schemas or None,
            tool_choice="auto" if schemas else None, temperature=0.0)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return {"episode_id": None, "final_content": msg.content,
                    "recorded": False, "tool_calls": tool_calls_made}
        for tc in msg.tool_calls:
            name = tc.function.name
            tool_calls_made.append(name)
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = funcs[name](**args)
                content = json.dumps(result, default=str)[:4000]
            except Exception as exc:  # surface tool errors back to the model
                content = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return {"episode_id": None, "final_content": messages[-1].get("content"),
            "recorded": False, "tool_calls": tool_calls_made}
