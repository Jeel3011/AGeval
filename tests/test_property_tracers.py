"""
tests/test_property_tracers.py

Property/fuzz tests for the framework adapters and error classifier.

Hypothesis drives the OpenAI + Anthropic tool-use loops with randomized scripted
model responses: variable numbers of tool calls, unknown tools, tool exceptions,
empty content, and deep loops up to max_iterations. The invariants:

  1. The loop always terminates and returns an episode_id (when configured).
  2. Every recorded step is well-formed (has the keys the API requires).
  3. reasoning is never an empty string on a tool step (the regression we fixed).
  4. The loop never raises for any combination of (n_turns, tool behaviour).

This is the "long-running / deep agent" stress at unit speed — no network.
"""

from __future__ import annotations

import types

from hypothesis import given, settings, strategies as st, HealthCheck

import ageval.session as session_mod
from ageval.session import classify_error
from ageval.openai_tracer import trace_openai
from ageval.anthropic_tracer import trace_anthropic


# ---------------------------------------------------------------------------
# Capture harness
# ---------------------------------------------------------------------------
class _Capture:
    def __init__(self):
        self.steps = []

    def post(self, path, payload, *, swallow=True):
        if path == "/steps/batch":
            self.steps.extend(payload)
        elif path == "/steps":
            self.steps.append(payload)
        return {"ok": True}


def _install(monkeypatch):
    cap = _Capture()
    monkeypatch.setenv("AGEVAL_API_KEY", "ageval-sk-test")
    monkeypatch.setattr(session_mod, "_post", cap.post)
    return cap


def _ok_tool(**kwargs):
    return {"result": "ok", "args": kwargs}


def _boom_tool(**kwargs):
    raise ValueError("boom")


# ---------------------------------------------------------------------------
# Scripted OpenAI client driven by a "plan": a list of turn specs.
# Each turn is either ("tool", tool_name) or ("stop",).
# ---------------------------------------------------------------------------
def _build_openai_client(plan):
    state = {"i": 0}

    def create(**kwargs):
        i = state["i"]
        state["i"] += 1
        spec = plan[i] if i < len(plan) else ("stop",)
        if spec[0] == "tool":
            tc = types.SimpleNamespace(
                id=f"c{i}",
                function=types.SimpleNamespace(name=spec[1], arguments="{}"),
            )
            msg = types.SimpleNamespace(content=None, tool_calls=[tc])
            msg.model_dump = lambda: {"role": "assistant", "content": None}
            choice = types.SimpleNamespace(message=msg, finish_reason="tool_calls")
        else:
            msg = types.SimpleNamespace(content="done", tool_calls=None)
            msg.model_dump = lambda: {"role": "assistant", "content": "done"}
            choice = types.SimpleNamespace(message=msg, finish_reason="stop")
        return types.SimpleNamespace(choices=[choice])

    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )


# A turn: tool-call to a known-good tool, a failing tool, an unknown tool, or stop.
_turn = st.sampled_from([
    ("tool", "good"),
    ("tool", "bad"),
    ("tool", "ghost"),   # not in tool_functions
    ("stop",),
])
plan_strategy = st.lists(_turn, min_size=0, max_size=12)


def _validate_step(s):
    # Every step must carry the keys the ingestion API requires.
    for key in ("episode_id", "step_index", "tool_name", "success"):
        assert key in s, f"step missing {key}: {s}"
    assert isinstance(s["step_index"], int)
    # Tool steps (not the llm_call bookkeeping step) must have non-empty reasoning.
    if s["tool_name"] not in ("llm_call",):
        assert s.get("reasoning"), f"tool step had empty reasoning: {s}"


@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(plan=plan_strategy)
def test_openai_loop_always_terminates_and_steps_valid(plan, monkeypatch):
    cap = _install(monkeypatch)
    result = trace_openai(
        client=_build_openai_client(plan),
        messages=[{"role": "user", "content": "do the thing"}],
        tools=[{"type": "function", "function": {"name": "good"}}],
        tool_functions={"good": _ok_tool, "bad": _boom_tool},
        agent_id="fuzz_openai",
        task="fuzz",
        max_iterations=12,
    )
    assert result["episode_id"]
    for s in cap.steps:
        _validate_step(s)


# ---------------------------------------------------------------------------
# Scripted Anthropic client
# ---------------------------------------------------------------------------
def _build_anthropic_client(plan):
    state = {"i": 0}

    def create(**kwargs):
        i = state["i"]
        state["i"] += 1
        spec = plan[i] if i < len(plan) else ("stop",)
        usage = types.SimpleNamespace(input_tokens=3, output_tokens=2)
        text = types.SimpleNamespace(type="text", text="thinking about it")
        if spec[0] == "tool":
            tu = types.SimpleNamespace(type="tool_use", id=f"tu{i}", name=spec[1], input={})
            return types.SimpleNamespace(content=[text, tu], stop_reason="tool_use", usage=usage)
        return types.SimpleNamespace(content=[text], stop_reason="end_turn", usage=usage)

    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create))


@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(plan=plan_strategy)
def test_anthropic_loop_always_terminates_and_steps_valid(plan, monkeypatch):
    cap = _install(monkeypatch)
    result = trace_anthropic(
        client=_build_anthropic_client(plan),
        messages=[{"role": "user", "content": "do the thing"}],
        tools=[{"name": "good", "input_schema": {}}],
        tool_functions={"good": _ok_tool, "bad": _boom_tool},
        agent_id="fuzz_anthropic",
        task="fuzz",
        max_iterations=12,
    )
    assert result["episode_id"]
    assert result["usage"]["output_tokens"] >= 0
    for s in cap.steps:
        _validate_step(s)


# ---------------------------------------------------------------------------
# Error classifier: never raises, always returns a valid (category, bool) tuple.
# ---------------------------------------------------------------------------
_VALID_CATEGORIES = {"agent_error", "env_error", "unknown"}


@settings(max_examples=300)
@given(msg=st.text(max_size=200))
def test_classify_error_total_function(msg):
    for exc in (ValueError(msg), TimeoutError(msg), RuntimeError(msg), KeyError(msg), Exception(msg)):
        cat, recoverable = classify_error(exc)
        assert cat in _VALID_CATEGORIES
        assert isinstance(recoverable, bool)
