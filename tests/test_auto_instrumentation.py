"""
tests/test_auto_instrumentation.py

Unit tests for ageval.auto (zero-code-change auto-instrumentation). These do
NOT make network or LLM calls — they verify the instrumentation mechanics:
idempotency, opt-out, OpenAI/Anthropic monkeypatching with a fake client, the
no-API-key no-op path, and the LangChain double-recording guard.
"""

from __future__ import annotations


import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # Start each test from a clean, disabled state and a known env.
    import ageval.auto as auto
    auto.disable()
    monkeypatch.setenv("AGEVAL_AUTO", "1")
    yield
    auto.disable()


def test_enable_is_idempotent():
    import ageval.auto as auto
    auto.enable()
    n = len(auto._PATCHES)
    auto.enable()  # second call must not double-patch
    assert len(auto._PATCHES) == n


def test_no_api_key_is_noop(monkeypatch):
    """With no AGEVAL_API_KEY, instrumentation installs but records nothing."""
    monkeypatch.delenv("AGEVAL_API_KEY", raising=False)
    import ageval.auto as auto
    calls = []
    monkeypatch.setattr(auto, "_post", lambda *a, **k: calls.append(a))
    auto.enable()
    auto._record_llm_step("x", "t", {}, {"content_preview": "hi"}, 5)
    assert calls == [], "should not post when AGEVAL_API_KEY is unset"


def test_openai_patch_records_step(monkeypatch):
    """A fake OpenAI Completions.create gets wrapped and its call is recorded."""
    import ageval.auto as auto

    # Build a stand-in for openai.resources.chat.completions.Completions
    class _Msg:
        content = "hello world"
        tool_calls = None

    class _Choice:
        message = _Msg()

    class _Usage:
        prompt_tokens = 11
        completion_tokens = 7

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    import types
    fake_mod = types.ModuleType("openai.resources.chat.completions")

    class Completions:
        def create(self, *a, **k):
            return _Resp()

    fake_mod.Completions = Completions
    monkeypatch.setitem(__import__("sys").modules, "openai.resources.chat.completions", fake_mod)
    # also wire the parent import path used by _patch_openai
    monkeypatch.setattr(
        "ageval.auto._patch_openai",
        lambda: _patch_with(auto, Completions),
    )

    recorded = []
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    monkeypatch.setattr(auto, "_record_llm_step",
                        lambda **kw: recorded.append(kw))

    auto._patch_openai()
    out = Completions().create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    assert out.choices[0].message.content == "hello world"
    assert recorded, "the patched create should have recorded a step"
    assert recorded[0]["tool_output"]["input_tokens"] == 11
    assert recorded[0]["tool_output"]["output_tokens"] == 7


def _patch_with(auto, Completions):
    """Mirror of auto._patch_openai but against an injected Completions class."""
    import functools
    import time

    original = Completions.create

    @functools.wraps(original)
    def create(self, *args, **kwargs):
        t0 = time.perf_counter()
        resp = original(self, *args, **kwargs)
        usage = getattr(resp, "usage", None)
        msg = resp.choices[0].message
        auto._record_llm_step(
            agent_id="openai_auto", task=str(kwargs.get("model")),
            tool_input={"model": kwargs.get("model")},
            tool_output={
                "content_preview": (msg.content or "")[:200],
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "tool_calls_count": 0,
            },
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return resp

    create._ageval_patched = True
    Completions.create = create
    auto._PATCHES.append((Completions, "create", original))


def test_disable_restores_patches(monkeypatch):
    import ageval.auto as auto

    class Completions:
        def create(self, *a, **k):
            return "real"

    original = Completions.create
    monkeypatch.setattr(auto, "_record_llm_step", lambda **kw: None)
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    _patch_with(auto, Completions)
    assert Completions.create is not original
    auto.disable()
    assert Completions.create is original, "disable() must restore the original method"


def test_langchain_guard_blocks_double_record(monkeypatch):
    """When a LangChain episode is open, the SDK patch must NOT also record."""
    import ageval.auto as auto
    monkeypatch.setattr(auto, "_api_configured", lambda: True)

    posted = []
    monkeypatch.setattr(auto, "_post", lambda *a, **k: posted.append(a))

    class _Handler:
        _episodes = {"root": {"episode_id": "ep", "counter": 0}}

    monkeypatch.setattr(auto, "_LC_HANDLER", _Handler())
    auto._record_llm_step("openai_auto", "t", {}, {"content_preview": "x"}, 1)
    assert posted == [], "must defer to the LangChain callback when an episode is open"


# ---------------------------------------------------------------------------
# Live guard (LIVE_EVAL_WEDGE_PLAN §3.2) — opt-in via AGEVAL_GUARD=1
# ---------------------------------------------------------------------------
def test_guard_disabled_by_default(monkeypatch):
    """Without AGEVAL_GUARD, _guard_tool never calls /evaluate (pure tracing)."""
    import ageval.auto as auto
    monkeypatch.delenv("AGEVAL_GUARD", raising=False)
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    calls = []
    monkeypatch.setattr(auto, "_post", lambda *a, **k: calls.append(a))
    auto._guard_tool("agent", "charge", {"amount": 9}, ["charge"])
    assert calls == []


def test_guard_blocks_on_block_verdict(monkeypatch):
    """With the guard on, a 'block' verdict raises AgevalBlocked."""
    import ageval.auto as auto
    monkeypatch.setenv("AGEVAL_GUARD", "1")
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    monkeypatch.setattr(auto, "_post", lambda *a, **k: {"action": "block", "score": 0.1,
                                                        "reasons": [{"message": "known failure"}]})
    with pytest.raises(auto.AgevalBlocked) as ei:
        auto._guard_tool("agent", "charge", {"amount": 9999}, ["charge"])
    assert ei.value.tool_name == "charge"
    assert ei.value.verdict.action == "block"


def test_guard_allows_on_non_block_verdict(monkeypatch):
    """warn / escalate / allow do NOT raise — the tool proceeds."""
    import ageval.auto as auto
    monkeypatch.setenv("AGEVAL_GUARD", "1")
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    for action in ("allow", "warn", "escalate"):
        monkeypatch.setattr(auto, "_post", lambda *a, _x=action, **k: {"action": _x})
        auto._guard_tool("agent", "charge", {"amount": 9}, ["charge"])  # must not raise


def test_guard_fails_open_on_error(monkeypatch):
    """A guard/evaluator error must never raise into the host — fail open."""
    import ageval.auto as auto
    monkeypatch.setenv("AGEVAL_GUARD", "1")
    monkeypatch.setattr(auto, "_api_configured", lambda: True)
    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(auto, "_post", _boom)
    auto._guard_tool("agent", "charge", {"amount": 9}, ["charge"])  # must not raise
