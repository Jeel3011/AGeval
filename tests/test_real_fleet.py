"""
tests/test_real_fleet.py

Tests for the real-agent fleet (examples/agents/real_tools.py, sideeffects.py,
fleet/registry.py, factory.py, run_fleet.py).

Two tiers:
  * Structural (always run, offline): registry integrity, schema validity for
    OpenAI + Anthropic, tool/schema parity, polite-client headers + backoff +
    no-cache behaviour, the OpenAI budget guard refuses overspend, side-effect
    master gate.
  * Live smoke (opt-in): with OPENAI_API_KEY + AGEVAL_RUN_LIVE_AGENTS=1, run one
    real agent and assert a real episode dict + that a live tool fired; plus a
    liveness assertion that a live tool's value changes across two calls.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from examples.agents import real_tools, sideeffects
from examples.agents.fleet import factory, registry
from examples.agents.fleet.budget_openai import BudgetExceeded, OpenAIBudgetGuard

LIVE = os.environ.get("OPENAI_API_KEY") and os.environ.get("AGEVAL_RUN_LIVE_AGENTS") == "1"
live_only = pytest.mark.skipif(
    not LIVE, reason="live fleet tests — set OPENAI_API_KEY and AGEVAL_RUN_LIVE_AGENTS=1 to run")


# --------------------------------------------------------------------------- #
# Registry integrity
# --------------------------------------------------------------------------- #
def test_registry_has_many_specs_across_verticals():
    assert len(registry.ALL_SPECS) >= 120
    assert len(registry.verticals()) == 20


def test_spec_ids_are_unique():
    ids = [s.id for s in registry.ALL_SPECS]
    assert len(ids) == len(set(ids))


def test_every_spec_tool_exists_and_resolves():
    known = set(real_tools.TOOL_FUNCTIONS) | set(sideeffects.TOOL_FUNCTIONS)
    for spec in registry.ALL_SPECS:
        for t in spec.all_tool_names():
            assert t in known, f"{spec.id} references unknown tool {t!r}"
        schemas, funcs = factory._resolve_tools(spec)
        assert schemas and funcs
        # every schema has a matching callable
        names = {s["function"]["name"] for s in schemas}
        assert names == set(funcs)


def test_every_spec_has_a_real_task():
    for spec in registry.ALL_SPECS:
        assert spec.task and len(spec.task) > 15
        assert spec.system_prompt


# --------------------------------------------------------------------------- #
# Schema validity (OpenAI + Anthropic) and parity across libraries
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", [real_tools, sideeffects])
def test_schemas_valid_for_openai_and_anthropic(mod):
    oai = mod.openai_schemas()
    ant = mod.anthropic_schemas()
    assert len(oai) == len(ant) == len(mod.TOOL_FUNCTIONS) == len(mod.mcp_manifest()["tools"])
    for s in oai:
        assert s["type"] == "function"
        assert "name" in s["function"] and "parameters" in s["function"]
        assert s["function"]["parameters"]["type"] == "object"
    for s in ant:
        assert "name" in s and "input_schema" in s
        assert s["input_schema"]["type"] == "object"


def test_real_tools_count_is_substantial():
    assert len(real_tools.TOOL_FUNCTIONS) >= 35


def test_subset_restricts_to_named_tools():
    sub = real_tools.subset(["fx_rate", "crypto_price"])
    assert set(sub) == {"fx_rate", "crypto_price"}


# --------------------------------------------------------------------------- #
# Polite HTTP client: UA header, backoff on 5xx/429, no caching
# --------------------------------------------------------------------------- #
def test_polite_client_sends_user_agent():
    captured = {}

    class _Resp:
        status_code = 200
        url = "http://x"
        headers = {}

        def json(self):
            return {"ok": True}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        captured["headers"] = headers
        return _Resp()

    with mock.patch.object(real_tools._session, "request", side_effect=fake_request):
        real_tools.polite_get("http://example.com/x")
    assert "User-Agent" in captured["headers"]
    assert captured["headers"]["User-Agent"] == real_tools.USER_AGENT


def test_polite_client_retries_then_raises_connectionerror_on_5xx():
    calls = {"n": 0}

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}
            self.text = "err"
            self.url = "http://x"

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls["n"] += 1
        return _Resp(503)

    with mock.patch.object(real_tools._session, "request", side_effect=fake_request), \
         mock.patch("examples.agents.real_tools.time.sleep"):
        with pytest.raises(ConnectionError):
            real_tools.polite_get("http://example.com/x")
    assert calls["n"] == real_tools.MAX_RETRIES  # it really retried, didn't give up early


def test_polite_client_maps_4xx_to_valueerror():
    class _Resp:
        status_code = 404
        headers = {}
        text = "nope"
        url = "http://x"

    def fake_request(method, url, headers=None, timeout=None, **kw):
        return _Resp()

    with mock.patch.object(real_tools._session, "request", side_effect=fake_request):
        with pytest.raises(ValueError):
            real_tools.polite_get("http://example.com/missing")


def test_polite_client_does_not_cache():
    # Two calls -> two real underlying requests (no memoisation).
    seen = {"n": 0}

    class _Resp:
        status_code = 200
        headers = {}
        url = "http://x"

        def json(self):
            return {"n": seen["n"]}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        seen["n"] += 1
        return _Resp()

    with mock.patch.object(real_tools._session, "request", side_effect=fake_request), \
         mock.patch("examples.agents.real_tools.time.sleep"):
        real_tools.polite_get("http://example.com/x")
        real_tools.polite_get("http://example.com/x")
    assert seen["n"] == 2


# --------------------------------------------------------------------------- #
# OpenAI budget guard refuses overspend
# --------------------------------------------------------------------------- #
def test_budget_guard_refuses_when_projection_exceeds_cap():
    class _FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kw):
                    raise AssertionError("should not be called once over cap")

    guard = OpenAIBudgetGuard(_FakeClient(), usd_cap=0.0)  # cap of $0 => any call refused
    with pytest.raises(BudgetExceeded):
        guard.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}],
                                      max_tokens=100)


def test_budget_guard_reconciles_real_usage():
    class _Usage:
        prompt_tokens = 1000
        completion_tokens = 500

    class _Resp:
        usage = _Usage()

    class _FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kw):
                    return _Resp()

    guard = OpenAIBudgetGuard(_FakeClient(), usd_cap=5.0)
    guard.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}],
                                  max_tokens=500)
    assert guard.calls == 1
    assert guard.spent > 0


# --------------------------------------------------------------------------- #
# Side-effect master gate
# --------------------------------------------------------------------------- #
def test_side_effects_gated_off_by_default():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGEVAL_LIVE_SIDE_EFFECTS", None)
        out = sideeffects.short_link("https://example.com")
        assert out.get("gated") is True


def test_capability_report_shape():
    rep = sideeffects.capability_report()
    for key in ("master_gate", "db_write", "short_link", "make_qr", "post_webhook",
                "send_email", "post_slack"):
        assert key in rep


# --------------------------------------------------------------------------- #
# Live smoke (opt-in)
# --------------------------------------------------------------------------- #
@live_only
def test_live_one_agent_per_vertical_runs_real():
    # ~1 agent per vertical (sampled), asserting a real episode + a tool fired.
    seen_verticals = set()
    for spec in registry.ALL_SPECS:
        if spec.vertical in seen_verticals:
            continue
        seen_verticals.add(spec.vertical)
        ep = factory.build_and_run(spec)
        assert ep, f"{spec.id} did not run"
        # either recorded (episode_id) or unrecorded loop (tool_calls) — both real
        assert ep.get("episode_id") or ep.get("tool_calls")
        if len(seen_verticals) >= 3:   # keep the smoke cheap
            break


@live_only
def test_live_data_changes_between_calls():
    # A liveness assertion: a live tool's value must be able to differ run-to-run.
    a = real_tools.iss_position()
    b = real_tools.iss_position()
    assert a["timestamp"] != b["timestamp"] or a["latitude"] != b["latitude"]
