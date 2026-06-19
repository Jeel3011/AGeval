"""
tests/test_workflows.py

Tests for the elaborate multi-stage workflows (Phase 2A) and the score-
provenance helper behind GET /episodes/{id}/explain (Phase 2B).

Structural tests run offline. The live workflow smoke is opt-in
(OPENAI_API_KEY + AGEVAL_RUN_LIVE_AGENTS=1).
"""

from __future__ import annotations

import os

import pytest

from examples.agents import real_tools, sideeffects
from examples.agents.fleet.workflows import registry

LIVE = os.environ.get("OPENAI_API_KEY") and os.environ.get("AGEVAL_RUN_LIVE_AGENTS") == "1"
live_only = pytest.mark.skipif(not LIVE, reason="set OPENAI_API_KEY and AGEVAL_RUN_LIVE_AGENTS=1")

_KNOWN_TOOLS = set(real_tools.TOOL_FUNCTIONS) | set(sideeffects.TOOL_FUNCTIONS)


# --------------------------------------------------------------------------- #
# Workflow registry integrity
# --------------------------------------------------------------------------- #
def test_workflows_exist_and_ids_unique():
    assert len(registry.ALL_WORKFLOWS) >= 18
    ids = [w.id for w in registry.ALL_WORKFLOWS]
    assert len(ids) == len(set(ids))


def test_every_workflow_is_multistep_ending_in_synthesis():
    for wf in registry.ALL_WORKFLOWS:
        assert len(wf.stages) >= 4, f"{wf.id} has < 4 stages"
        # at least 3 real tool stages -> a real ≥4-step trajectory once synthesis lands
        tool_stages = [s for s in wf.stages if s.kind == "tool"]
        assert len(tool_stages) >= 3, f"{wf.id} has < 3 tool stages"
        # there is an LLM synthesis/decision stage (some workflows then *act* on
        # it with a final side-effect stage, which is fine).
        llm_stages = [s for s in wf.stages if s.kind == "llm"]
        assert len(llm_stages) >= 1, f"{wf.id} has no llm synthesis stage"
        last = wf.stages[-1]
        assert last.kind == "llm" or last.tool in sideeffects.TOOL_FUNCTIONS, \
            f"{wf.id} should end in synthesis or a side-effect action"


def test_every_workflow_tool_exists():
    for wf in registry.ALL_WORKFLOWS:
        for st in wf.stages:
            if st.tool is not None:
                assert st.tool in _KNOWN_TOOLS, f"{wf.id}:{st.name} unknown tool {st.tool!r}"


def test_workflow_arg_builders_are_callable_on_empty_context():
    # Each tool stage's args() must not explode on a fresh context (defaults).
    for wf in registry.ALL_WORKFLOWS:
        for st in wf.stages:
            if st.kind == "tool" and st.args is not None:
                out = st.args({"goal": wf.goal})
                assert isinstance(out, dict)
            if st.kind == "llm":
                assert callable(st.llm_prompt)
                assert isinstance(st.llm_prompt({"goal": wf.goal}), str)


def test_side_effect_workflows_flagged():
    se = [w for w in registry.ALL_WORKFLOWS if w.fires_side_effects()]
    assert se, "expected at least one workflow that fires real side effects"
    for w in se:
        assert any(s.tool in sideeffects.TOOL_FUNCTIONS for s in w.stages)


def test_workflows_span_many_verticals():
    assert len(registry.verticals()) >= 15


# --------------------------------------------------------------------------- #
# Score-provenance helper (the engine behind /episodes/{id}/explain)
# --------------------------------------------------------------------------- #
def test_score_provenance_ranks_worst_metric_first():
    from main import _score_provenance

    scores = [{
        "scorer": "rules",
        "score": 0.8,
        "breakdown": {"success_rate": 1.0, "reasoning_coverage": 0.4, "efficiency_score": 0.9},
    }]
    prov = _score_provenance(scores)
    assert len(prov) == 1
    top = prov[0]["top_drivers"]
    # the metric with the biggest shortfall (reasoning_coverage, 0.6) comes first
    assert top[0]["metric"] == "reasoning_coverage"
    assert top[0]["shortfall"] == pytest.approx(0.6, abs=1e-6)
    # perfect metric has zero shortfall
    assert any(c["metric"] == "success_rate" and c["shortfall"] == 0.0 for c in top)


def test_score_provenance_handles_empty_and_nonnumeric():
    from main import _score_provenance

    assert _score_provenance([]) == []
    prov = _score_provenance([{"scorer": "x", "score": None,
                               "breakdown": {"note": "n/a", "ok": 1.0}}])
    metrics = [c["metric"] for c in prov[0]["all_metrics"]]
    assert metrics == ["ok"]  # non-numeric "note" dropped


# --------------------------------------------------------------------------- #
# Live workflow smoke (opt-in)
# --------------------------------------------------------------------------- #
@live_only
def test_live_workflow_records_multistep_trajectory():
    from examples.agents.fleet.workflows.base import run_workflow

    wf = registry.get("wf.finance.ma_diligence")
    ep = run_workflow(wf)
    assert ep, "workflow did not run"
    assert ep["steps"] >= 4, "expected a real multi-step trajectory"
    assert ep["trajectory"], "trajectory should be populated"
    # every stage carries a live verdict action (transparency)
    assert all("verdict_action" in t for t in ep["trajectory"])
