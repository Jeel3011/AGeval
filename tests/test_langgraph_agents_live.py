"""
tests/test_langgraph_agents_live.py

LIVE consistency + reliability tests for the LangGraph example agents.

These run REAL LangGraph agents with REAL OpenAI calls and score them with the
REAL AGeval metric functions, then assert that AGeval:

  1. is CONSISTENT — the same agent scored across repeated runs stays in the
     same band (small spread on the deterministic, structural metrics);
  2. is RELIABLE across LangGraph state regimes — single-loop, long-running,
     and supervised multi-agent graphs all produce sane, well-formed episodes;
  3. SEPARATES good agents from failing ones — the intentionally-broken agents
     (20 stuck-retry, 21 bad-args) score materially worse and, crucially, are
     attributed to the RIGHT failure class (env vs agent error). That last
     point is the whole reason this product exists.

They are OPT-IN (they cost OpenAI tokens) and skipped unless BOTH:
    OPENAI_API_KEY is set, and  AGEVAL_RUN_LIVE_AGENTS=1
So the default `pytest` run (CI, no key) collects but skips them.

    AGEVAL_RUN_LIVE_AGENTS=1 pytest tests/test_langgraph_agents_live.py -v
"""

from __future__ import annotations

import os

import pytest

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

pytestmark = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("AGEVAL_RUN_LIVE_AGENTS") == "1"),
    reason="live agent tests — set OPENAI_API_KEY and AGEVAL_RUN_LIVE_AGENTS=1 to run",
)

AGENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "agents")


def _harness():
    import sys
    root = os.path.dirname(AGENTS).rsplit(os.sep, 1)[0]
    if root not in sys.path:
        sys.path.insert(0, root)
    from examples.agents import _harness  # noqa: WPS433
    return _harness


def _path(stem: str) -> str:
    return os.path.join(AGENTS, stem + ".py")


# --------------------------------------------------------------------------
# Reliability across LangGraph state regimes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stem,min_steps", [
    ("09_langgraph_support_router", 2),
    ("18_langgraph_long_research", 8),       # long-running: many steps
    ("19_langgraph_supervisor_team", 4),     # supervised multi-agent
])
def test_good_langgraph_agents_are_well_formed(stem, min_steps):
    h = _harness()
    r = h.run_agent_capture(_path(stem))
    assert not r.get("skipped"), f"{stem} did not run"
    ep = r["episode"]
    assert ep["total_steps"] >= min_steps, f"{stem}: too few steps ({ep['total_steps']})"
    # Every metric must be a clean, bounded number (no None-arithmetic crashes).
    for name, val in r["metrics"].items():
        assert isinstance(val, float) and 0.0 <= val <= 1.0, f"{stem}.{name}={val} out of range"
    # A working agent should land cleanly and make essentially no agent errors.
    assert r["metrics"]["last_call_success"] == 1.0, f"{stem} did not land on a successful step"
    assert r["metrics"]["agent_error_rate"] >= 0.8, f"{stem} had too many agent errors"
    assert ep["outcome"] in {"success", "partial"}, f"{stem} outcome={ep['outcome']}"


def test_long_running_agent_actually_runs_long():
    """The long-running graph must produce a high-volume episode and still be
    scored without latency/None arithmetic issues."""
    h = _harness()
    r = h.run_agent_capture(_path("18_langgraph_long_research"))
    assert not r.get("skipped")
    assert r["episode"]["total_steps"] >= 8
    assert r["episode"]["total_latency_ms"] >= 0  # aggregation is None-safe


# --------------------------------------------------------------------------
# Consistency across repeated runs
# --------------------------------------------------------------------------
def test_router_is_consistent_across_runs():
    """Same agent, repeated runs → the structural metrics stay in a tight band.
    (temperature=0, so behaviour should be stable.)"""
    h = _harness()
    runs = h.repeat(_path("09_langgraph_support_router"), 2)
    assert len(runs) == 2, "router did not run twice"
    summary = h.summarize(runs, ["agent_error_rate", "last_call_success"])
    # No agent errors on either run; both land successfully.
    assert summary["agent_error_rate"]["min"] >= 0.8
    assert summary["last_call_success"]["min"] == 1.0
    # Outcomes agree across runs.
    outcomes = {r["outcome"] for r in runs}
    assert len(outcomes) == 1, f"router outcome flapped across runs: {outcomes}"


# --------------------------------------------------------------------------
# The point of the product: failing agents are caught AND correctly attributed
# --------------------------------------------------------------------------
def test_failing_retry_loop_is_caught_as_env_failure():
    h = _harness()
    r = h.run_agent_capture(_path("20_langgraph_failing_retry_loop"))
    assert not r.get("skipped")
    m = r["metrics"]
    # It failed…
    assert r["outcome"] == "failure", f"expected failure, got {r['outcome']}"
    assert m["last_call_success"] == 0.0
    # …and it's an ENVIRONMENT failure (flaky backend), not the agent's logic.
    # env_error_rate metric = 1 - env_errors/steps → low means lots of env errors.
    assert m["env_error_rate"] <= 0.3, f"should be dominated by env errors, got {m['env_error_rate']}"
    assert m["agent_error_rate"] >= 0.8, "must NOT be misattributed as agent errors"


def test_failing_bad_args_is_caught_as_agent_failure():
    h = _harness()
    r = h.run_agent_capture(_path("21_langgraph_failing_bad_args"))
    assert not r.get("skipped")
    m = r["metrics"]
    assert r["outcome"] == "failure", f"expected failure, got {r['outcome']}"
    assert m["last_call_success"] == 0.0
    # …and it's an AGENT failure (bad arguments), not a flaky environment.
    assert m["agent_error_rate"] <= 0.3, f"should be dominated by agent errors, got {m['agent_error_rate']}"
    assert m["env_error_rate"] >= 0.8, "must NOT be misattributed as env errors"


def test_good_vs_failing_separation():
    """A good agent must outscore the failing ones on landing + outcome —
    the core signal an eval platform has to deliver."""
    h = _harness()
    good = h.run_agent_capture(_path("09_langgraph_support_router"))
    bad1 = h.run_agent_capture(_path("20_langgraph_failing_retry_loop"))
    bad2 = h.run_agent_capture(_path("21_langgraph_failing_bad_args"))
    for r in (good, bad1, bad2):
        assert not r.get("skipped")
    assert good["metrics"]["last_call_success"] == 1.0
    assert bad1["metrics"]["last_call_success"] == 0.0
    assert bad2["metrics"]["last_call_success"] == 0.0
    assert good["outcome"] in {"success", "partial"}
    assert bad1["outcome"] == "failure" and bad2["outcome"] == "failure"
