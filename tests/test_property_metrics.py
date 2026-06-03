"""
tests/test_property_metrics.py

Property-based (Hypothesis) tests for the scoring layer.

The contract every metric must uphold, no matter what garbage it's fed:
  1. It returns a float in [0.0, 1.0].
  2. It never raises (a malformed step must not crash scoring).
  3. It is deterministic for the same input.

Hypothesis generates thousands of step-list shapes — missing keys, None values,
wrong types, huge lists, negative latencies, duplicate indices — and runs every
registered metric, the rule scorer, and the custom-metrics composite against
them. This is the "every possibility" sweep.
"""

from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st, HealthCheck

from ageval import metrics as M
from eval import rules as R


# ---------------------------------------------------------------------------
# Strategy: an arbitrary, possibly-malformed "step" dict.
# We deliberately allow missing/None/wrong-typed fields.
# ---------------------------------------------------------------------------
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=50),
)

_tool_output = st.one_of(
    st.none(),
    st.text(max_size=80),
    st.dictionaries(st.text(max_size=10), _json_scalars, max_size=5),
    st.lists(_json_scalars, max_size=5),
)

step_strategy = st.fixed_dictionaries(
    {},
    optional={
        "step_index": st.integers(min_value=-5, max_value=50),
        "tool_name": st.one_of(st.none(), st.sampled_from(["a", "b", "search", "llm_call", ""])),
        "tool_input": _tool_output,
        "tool_output": _tool_output,
        "success": st.one_of(st.none(), st.booleans()),
        "error_category": st.one_of(st.none(), st.sampled_from(["agent_error", "env_error", "unknown", "weird"])),
        "is_recoverable": st.one_of(st.none(), st.booleans()),
        "reasoning": st.one_of(st.none(), st.text(max_size=300)),
        "latency_ms": st.one_of(st.none(), st.integers(min_value=-100, max_value=120_000)),
    },
)

steps_strategy = st.lists(step_strategy, max_size=25)

# Every metric function registered in the catalogue.
ALL_METRIC_FNS = [v["fn"] for v in M._registry.values()]
ALL_METRIC_NAMES = list(M._registry.keys())

# Rule scorer component functions (operate on steps, return [0,1]).
RULE_FNS = [
    R.calc_success_rate,
    R.calc_recovery_rate,
    R.calc_reasoning_coverage,
    R.calc_efficiency_score,
]


def _assert_unit(value, label):
    assert isinstance(value, (int, float)), f"{label} returned non-numeric {value!r}"
    assert not math.isnan(value), f"{label} returned NaN"
    assert 0.0 - 1e-9 <= value <= 1.0 + 1e-9, f"{label} out of [0,1]: {value}"


@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
@given(steps=steps_strategy)
def test_every_registered_metric_is_bounded_and_safe(steps):
    """Each registered metric stays in [0,1] and never raises, for any steps."""
    episode = {"agent_id": "a", "task": "t", "outcome": "success"}
    for name, fn in zip(ALL_METRIC_NAMES, ALL_METRIC_FNS):
        value = fn(steps, episode)  # must not raise
        _assert_unit(value, f"metric {name}")


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(steps=steps_strategy)
def test_rule_scorer_components_bounded(steps):
    """Rule scorer component fns stay in [0,1] for any non-empty steps."""
    # calc_* functions assume at least one step (the caller guards empty lists).
    if not steps:
        return
    # Several rule fns key into s["step_index"]/s["tool_name"] directly, so they
    # require those keys — mirror what fetch_steps guarantees in production.
    norm = [
        {**s, "step_index": s.get("step_index", i), "tool_name": s.get("tool_name") or "tool"}
        for i, s in enumerate(steps)
    ]
    for fn in RULE_FNS:
        _assert_unit(fn(norm), f"rule {fn.__name__}")


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(steps=steps_strategy)
def test_metrics_are_deterministic(steps):
    """Same input → same output (no hidden randomness/state)."""
    episode = {"agent_id": "a"}
    for name, fn in zip(ALL_METRIC_NAMES, ALL_METRIC_FNS):
        a = fn(steps, episode)
        b = fn(steps, episode)
        assert a == b, f"metric {name} non-deterministic: {a} != {b}"


@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(steps=steps_strategy)
def test_custom_composite_via_fake_db_is_bounded(steps):
    """The full score_with_custom_metrics composite stays in [0,1] end-to-end."""
    from tests.fakes import FakeSupabase
    if not steps:
        return
    # Give each step a unique index so the unique(episode_id, step_index) holds.
    norm = [{**s, "step_index": i, "episode_id": "ep_p"} for i, s in enumerate(steps)]
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "ep_p", "agent_id": "a", "task": "t", "outcome": "success", "user_id": "u"}])
    db.seed("episode_steps", norm)
    result = M.score_with_custom_metrics(db, "ep_p")
    _assert_unit(result["score"], "custom composite")
    for k, v in result["breakdown"].items():
        _assert_unit(v, f"breakdown[{k}]")


# ---------------------------------------------------------------------------
# Targeted invariants that should hold by construction.
# ---------------------------------------------------------------------------
@settings(max_examples=100)
@given(n=st.integers(min_value=1, max_value=25))
def test_all_success_gives_perfect_success_rate(n):
    steps = [{"step_index": i, "tool_name": "t", "success": True} for i in range(n)]
    assert R.calc_success_rate(steps) == 1.0
    assert M.agent_error_rate(steps, {}) == 1.0


@settings(max_examples=100)
@given(n=st.integers(min_value=2, max_value=25))
def test_all_duplicate_tool_tanks_efficiency(n):
    steps = [{"step_index": i, "tool_name": "same", "success": True} for i in range(n)]
    # Every consecutive pair is a duplicate → efficiency 0.0.
    assert R.calc_efficiency_score(steps) == 0.0
    # And backtrack_rate: identical (tool,input) every time → 0.0.
    assert M.backtrack_rate(steps, {}) == 0.0
