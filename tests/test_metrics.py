"""
tests/test_metrics.py

Tests for the custom metric registry.
"""

from __future__ import annotations

import pytest

from ageval.metrics import (
    _registry,
    register_metric,
    unregister_metric,
    list_metrics,
    get_metric,
    tool_diversity,
    latency_budget,
    error_recovery_speed,
    agent_error_rate,
    env_error_rate,
    fatal_error_rate,
    first_call_success,
    last_call_success,
    step_economy,
    p95_step_latency,
    retry_overhead,
    tool_call_precision,
    goal_progress,
    reasoning_depth,
    multi_tool_usage,
    output_richness,
    backtrack_rate,
    token_economy,
    reasoning_action_alignment,
)


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------
class TestMetricRegistry:
    def setup_method(self):
        """Save registry state before each test."""
        self._saved = dict(_registry)

    def teardown_method(self):
        """Restore registry state after each test."""
        _registry.clear()
        _registry.update(self._saved)

    def test_register_and_list(self):
        @register_metric("test_metric_1", weight=0.5, description="A test metric")
        def my_metric(steps, episode):
            return 0.5

        metrics = list_metrics()
        names = [m["name"] for m in metrics]
        assert "test_metric_1" in names

    def test_unregister(self):
        @register_metric("temp_metric", weight=0.1)
        def temp(steps, episode):
            return 1.0

        assert get_metric("temp_metric") is not None
        assert unregister_metric("temp_metric") is True
        assert get_metric("temp_metric") is None
        assert unregister_metric("temp_metric") is False  # already gone

    def test_overwrite_warning(self):
        @register_metric("dup_metric")
        def v1(steps, episode):
            return 0.1

        @register_metric("dup_metric")
        def v2(steps, episode):
            return 0.9

        fn = get_metric("dup_metric")
        # Should be v2 (overwritten)
        assert fn([], {}) == 0.9


# ---------------------------------------------------------------------------
# Built-in metrics
# ---------------------------------------------------------------------------
class TestBuiltInMetrics:
    def test_tool_diversity_all_unique(self):
        steps = [
            {"tool_name": "search"},
            {"tool_name": "fetch"},
            {"tool_name": "parse"},
        ]
        assert tool_diversity(steps, {}) == 1.0

    def test_tool_diversity_all_same(self):
        steps = [
            {"tool_name": "search"},
            {"tool_name": "search"},
            {"tool_name": "search"},
        ]
        score = tool_diversity(steps, {})
        assert score == pytest.approx(0.3333, abs=0.01)

    def test_tool_diversity_empty(self):
        assert tool_diversity([], {}) == 0.0

    def test_latency_budget_fast(self):
        steps = [{"latency_ms": 100}, {"latency_ms": 200}]
        assert latency_budget(steps, {}) == 1.0  # 300ms total = under 5s

    def test_latency_budget_slow(self):
        steps = [{"latency_ms": 60000}]  # 60s
        assert latency_budget(steps, {}) == 0.0

    def test_latency_budget_medium(self):
        steps = [{"latency_ms": 30000}]  # 30s
        score = latency_budget(steps, {})
        assert 0.0 < score < 1.0

    def test_error_recovery_speed_no_errors(self):
        steps = [
            {"step_index": 0, "success": True},
            {"step_index": 1, "success": True},
        ]
        assert error_recovery_speed(steps, {}) == 1.0

    def test_error_recovery_speed_immediate(self):
        steps = [
            {"step_index": 0, "success": True},
            {"step_index": 1, "success": False, "error_category": "env_error"},
            {"step_index": 2, "success": True},
        ]
        # Immediate recovery (1 step gap) = 1.0
        assert error_recovery_speed(steps, {}) == 1.0

    def test_error_recovery_speed_slow(self):
        steps = [
            {"step_index": 0, "success": False, "error_category": "env_error"},
            {"step_index": 1, "success": False, "error_category": "env_error"},
            {"step_index": 2, "success": False, "error_category": "env_error"},
            {"step_index": 3, "success": False, "error_category": "env_error"},
            {"step_index": 4, "success": True},
        ]
        score = error_recovery_speed(steps, {})
        assert score < 1.0  # Took a while to recover


# ---------------------------------------------------------------------------
# New reliability metrics
# ---------------------------------------------------------------------------
class TestReliabilityMetrics:
    def test_agent_error_rate_none(self):
        steps = [{"success": True, "error_category": None},
                 {"success": True, "error_category": None}]
        assert agent_error_rate(steps, {}) == 1.0

    def test_agent_error_rate_all(self):
        steps = [{"success": False, "error_category": "agent_error"},
                 {"success": False, "error_category": "agent_error"}]
        assert agent_error_rate(steps, {}) == 0.0

    def test_agent_error_rate_partial(self):
        steps = [{"success": False, "error_category": "agent_error"},
                 {"success": True,  "error_category": None}]
        assert agent_error_rate(steps, {}) == 0.5

    def test_env_error_rate_clean(self):
        steps = [{"success": True, "error_category": None}]
        assert env_error_rate(steps, {}) == 1.0

    def test_env_error_rate_flaky(self):
        steps = [{"success": False, "error_category": "env_error"},
                 {"success": False, "error_category": "env_error"},
                 {"success": True,  "error_category": None}]
        assert env_error_rate(steps, {}) == pytest.approx(1 - 2/3, abs=0.001)

    def test_fatal_error_rate_all_recoverable(self):
        steps = [{"success": False, "is_recoverable": True},
                 {"success": False, "is_recoverable": True}]
        assert fatal_error_rate(steps, {}) == 1.0

    def test_fatal_error_rate_all_fatal(self):
        steps = [{"success": False, "is_recoverable": False}]
        assert fatal_error_rate(steps, {}) == 0.0

    def test_fatal_error_rate_no_failures(self):
        steps = [{"success": True}]
        assert fatal_error_rate(steps, {}) == 1.0

    def test_first_call_success_true(self):
        steps = [{"step_index": 0, "success": True},
                 {"step_index": 1, "success": False}]
        assert first_call_success(steps, {}) == 1.0

    def test_first_call_success_false(self):
        steps = [{"step_index": 0, "success": False},
                 {"step_index": 1, "success": True}]
        assert first_call_success(steps, {}) == 0.0

    def test_last_call_success_true(self):
        steps = [{"step_index": 0, "success": False},
                 {"step_index": 1, "success": True}]
        assert last_call_success(steps, {}) == 1.0

    def test_last_call_success_false(self):
        steps = [{"step_index": 0, "success": True},
                 {"step_index": 1, "success": False}]
        assert last_call_success(steps, {}) == 0.0


# ---------------------------------------------------------------------------
# Cost / efficiency metrics
# ---------------------------------------------------------------------------
class TestCostMetrics:
    def test_step_economy_compact(self):
        steps = [{"step_index": i} for i in range(2)]
        assert step_economy(steps, {}) == 1.0

    def test_step_economy_bloated(self):
        steps = [{"step_index": i} for i in range(20)]
        assert step_economy(steps, {}) == 0.0

    def test_step_economy_medium(self):
        steps = [{"step_index": i} for i in range(10)]
        score = step_economy(steps, {})
        assert 0.0 < score < 1.0

    def test_p95_step_latency_fast(self):
        steps = [{"latency_ms": 200}] * 20
        assert p95_step_latency(steps, {}) == 1.0

    def test_p95_step_latency_slow(self):
        steps = [{"latency_ms": 20_000}] * 5
        assert p95_step_latency(steps, {}) == 0.0

    def test_p95_step_latency_mixed(self):
        # Put slow steps at the top so p95 lands on them.
        # With 10 steps, p95_idx = max(0, int(10*0.95)-1) = 8 (0-indexed), i.e. the 9th value.
        # sorted: [200]*8 + [5000, 8000] → p95 value = 5000ms → between 1s and 15s
        steps = [{"latency_ms": 200}] * 8 + [{"latency_ms": 5_000}, {"latency_ms": 8_000}]
        score = p95_step_latency(steps, {})
        assert 0.0 < score < 1.0

    def test_retry_overhead_none(self):
        steps = [
            {"step_index": 0, "success": True,  "tool_name": "a"},
            {"step_index": 1, "success": True,  "tool_name": "b"},
        ]
        assert retry_overhead(steps, {}) == 1.0

    def test_retry_overhead_all_retries(self):
        steps = [
            {"step_index": 0, "success": False, "tool_name": "search"},
            {"step_index": 1, "success": False, "tool_name": "search"},
            {"step_index": 2, "success": False, "tool_name": "search"},
        ]
        assert retry_overhead(steps, {}) == 0.0

    def test_retry_overhead_partial(self):
        steps = [
            {"step_index": 0, "success": False, "tool_name": "a"},
            {"step_index": 1, "success": True,  "tool_name": "a"},  # retry
            {"step_index": 2, "success": True,  "tool_name": "b"},  # advance
        ]
        assert retry_overhead(steps, {}) == pytest.approx(0.5, abs=0.001)


# ---------------------------------------------------------------------------
# Agentic / goal-oriented metrics
# ---------------------------------------------------------------------------
class TestAgenticMetrics:
    def test_tool_call_precision_all_success_unique(self):
        steps = [
            {"success": True, "tool_name": "search"},
            {"success": True, "tool_name": "parse"},
            {"success": True, "tool_name": "send"},
        ]
        assert tool_call_precision(steps, {}) == 1.0

    def test_tool_call_precision_with_failures(self):
        steps = [
            {"success": True,  "tool_name": "search"},
            {"success": False, "tool_name": "parse"},
            {"success": True,  "tool_name": "send"},
        ]
        # 2 unique successful tools / 3 total steps
        assert tool_call_precision(steps, {}) == pytest.approx(2/3, abs=0.001)

    def test_goal_progress_all_advance(self):
        steps = [
            {"step_index": 0, "tool_name": "a"},
            {"step_index": 1, "tool_name": "b"},
            {"step_index": 2, "tool_name": "c"},
        ]
        assert goal_progress(steps, {}) == 1.0

    def test_goal_progress_no_advance(self):
        steps = [
            {"step_index": 0, "tool_name": "a"},
            {"step_index": 1, "tool_name": "a"},
            {"step_index": 2, "tool_name": "a"},
        ]
        assert goal_progress(steps, {}) == 0.0

    def test_reasoning_depth_no_reasoning(self):
        steps = [{"reasoning": None}, {"reasoning": ""}]
        assert reasoning_depth(steps, {}) == 0.0

    def test_reasoning_depth_full(self):
        # 200+ char reasoning on every step
        steps = [{"reasoning": "x" * 200}, {"reasoning": "y" * 300}]
        assert reasoning_depth(steps, {}) == 1.0

    def test_reasoning_depth_partial(self):
        steps = [{"reasoning": "x" * 100}, {"reasoning": None}]
        score = reasoning_depth(steps, {})
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Memory / output richness metrics
# ---------------------------------------------------------------------------
class TestMemoryMetrics:
    def test_multi_tool_no_steps(self):
        assert multi_tool_usage([], {}) == 0.0

    def test_multi_tool_single(self):
        steps = [{"tool_name": "search"}, {"tool_name": "search"}]
        assert multi_tool_usage(steps, {}) == 0.5

    def test_multi_tool_diverse(self):
        steps = [{"tool_name": "search"}, {"tool_name": "parse"}]
        assert multi_tool_usage(steps, {}) == 1.0

    def test_output_richness_no_outputs(self):
        steps = [{"success": False, "tool_output": None}]
        assert output_richness(steps, {}) == 0.0

    def test_output_richness_rich(self):
        # 500+ chars of JSON output
        steps = [{"success": True, "tool_output": {"data": "x" * 500}}]
        assert output_richness(steps, {}) == 1.0

    def test_output_richness_minimal(self):
        steps = [{"success": True, "tool_output": "ok"}]
        score = output_richness(steps, {})
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Backtracking / cost metrics
# ---------------------------------------------------------------------------
class TestBacktrackCostMetrics:
    def test_backtrack_none(self):
        steps = [
            {"step_index": 0, "tool_name": "search", "tool_input": {"q": "a"}},
            {"step_index": 1, "tool_name": "search", "tool_input": {"q": "b"}},
            {"step_index": 2, "tool_name": "parse", "tool_input": {"q": "a"}},
        ]
        assert backtrack_rate(steps, {}) == 1.0

    def test_backtrack_repeats_exact_input(self):
        # Same tool + identical input called 3 times → 2 repeats out of 2 transitions.
        steps = [
            {"step_index": 0, "tool_name": "search", "tool_input": {"q": "a"}},
            {"step_index": 1, "tool_name": "search", "tool_input": {"q": "a"}},
            {"step_index": 2, "tool_name": "search", "tool_input": {"q": "a"}},
        ]
        assert backtrack_rate(steps, {}) == 0.0

    def test_backtrack_single_step(self):
        assert backtrack_rate([{"step_index": 0, "tool_name": "x"}], {}) == 1.0

    def test_token_economy_no_usage(self):
        # No token usage recorded → nothing to penalize.
        steps = [{"tool_name": "search", "tool_output": {"results": []}}]
        assert token_economy(steps, {}) == 1.0

    def test_token_economy_cheap(self):
        steps = [{"tool_name": "llm_call", "tool_output": {"input_tokens": 500, "output_tokens": 200}}]
        assert token_economy(steps, {}) == 1.0

    def test_token_economy_expensive(self):
        steps = [{"tool_name": "llm_call", "tool_output": {"input_tokens": 40000, "output_tokens": 20000}}]
        assert token_economy(steps, {}) == 0.0

    def test_token_economy_medium(self):
        steps = [{"tool_name": "llm_call", "tool_output": {"input_tokens": 10000, "output_tokens": 5000}}]
        score = token_economy(steps, {})
        assert 0.0 < score < 1.0

    def test_reasoning_action_alignment_perfect(self):
        steps = [
            {"tool_name": "search", "success": True, "reasoning": "need data"},
            {"tool_name": "parse", "success": True, "reasoning": "extract it"},
        ]
        assert reasoning_action_alignment(steps, {}) == 1.0

    def test_reasoning_action_alignment_no_reasoning(self):
        steps = [
            {"tool_name": "search", "success": True, "reasoning": None},
            {"tool_name": "parse", "success": True, "reasoning": ""},
        ]
        assert reasoning_action_alignment(steps, {}) == 0.0

    def test_reasoning_action_alignment_ignores_llm_call(self):
        # llm_call steps are excluded; only the real tool step counts.
        steps = [
            {"tool_name": "llm_call", "success": True, "reasoning": "thinking"},
            {"tool_name": "search", "success": True, "reasoning": "go"},
        ]
        assert reasoning_action_alignment(steps, {}) == 1.0


# ---------------------------------------------------------------------------
# Deep evaluation metrics (v2)
# ---------------------------------------------------------------------------
class TestDeepMetrics:
    def _g(self, name, steps, episode=None):
        return get_metric(name)(steps, episode or {})

    def test_recovery_success_rate(self):
        # fail → success → fail → fail : two "after a failure" steps, one recovers
        steps = [
            {"tool_name": "a", "success": False},
            {"tool_name": "a", "success": True},
            {"tool_name": "b", "success": False},
            {"tool_name": "b", "success": False},
        ]
        assert self._g("recovery_success_rate", steps) == 0.5

    def test_recovery_success_rate_nothing_to_recover(self):
        steps = [{"tool_name": "a", "success": True}, {"tool_name": "b", "success": True}]
        assert self._g("recovery_success_rate", steps) == 1.0

    def test_failure_clustering_isolated_vs_clustered(self):
        clustered = [{"tool_name": "x", "success": False} for _ in range(3)]
        assert self._g("failure_clustering", clustered) == 0.0
        isolated = [
            {"tool_name": "x", "success": False},
            {"tool_name": "y", "success": True},
            {"tool_name": "z", "success": False},
        ]
        assert self._g("failure_clustering", isolated) == 1.0

    def test_tool_selection_entropy(self):
        balanced = [{"tool_name": t, "success": True} for t in ["a", "b", "c", "a", "b", "c"]]
        assert self._g("tool_selection_entropy", balanced) == 1.0
        single = [{"tool_name": "a", "success": True} for _ in range(5)]
        assert self._g("tool_selection_entropy", single) == 1.0  # one tool → trivially balanced
        skewed = [{"tool_name": "a", "success": True}] * 9 + [{"tool_name": "b", "success": True}]
        assert self._g("tool_selection_entropy", skewed) < 0.6

    def test_progress_monotonicity(self):
        thrash = [{"tool_name": "a", "success": True} for _ in range(3)]
        assert self._g("progress_monotonicity", thrash) < 0.5
        forward = [{"tool_name": t, "success": True} for t in ["a", "b", "c"]]
        assert self._g("progress_monotonicity", forward) == 1.0

    def test_cost_per_success(self):
        # no tokens recorded → 1.0
        assert self._g("cost_per_success", [{"tool_name": "a", "success": True}]) == 1.0
        # lean: 500 tokens, 1 success
        lean = [{"tool_name": "llm_call", "success": True,
                 "tool_output": {"input_tokens": 400, "output_tokens": 100}},
                {"tool_name": "a", "success": True}]
        assert self._g("cost_per_success", lean) == 1.0
        # tokens burned, zero successes → 0.0
        burned = [{"tool_name": "llm_call", "success": True,
                   "tool_output": {"input_tokens": 5000, "output_tokens": 5000}},
                  {"tool_name": "a", "success": False}]
        assert self._g("cost_per_success", burned) == 0.0

    def test_latency_consistency(self):
        steady = [{"tool_name": "a", "success": True, "latency_ms": 100} for _ in range(4)]
        assert self._g("latency_consistency", steady) == 1.0
        erratic = [
            {"tool_name": "a", "success": True, "latency_ms": 10},
            {"tool_name": "a", "success": True, "latency_ms": 5000},
        ]
        assert self._g("latency_consistency", erratic) < 0.5

    def test_error_concentration(self):
        assert self._g("error_concentration", [{"tool_name": "a", "success": True}]) == 1.0
        one_tool = [{"tool_name": "x", "success": False} for _ in range(4)]
        assert self._g("error_concentration", one_tool) == 1.0
        spread = [
            {"tool_name": "a", "success": False},
            {"tool_name": "b", "success": False},
            {"tool_name": "c", "success": False},
            {"tool_name": "d", "success": False},
        ]
        assert self._g("error_concentration", spread) == 0.25

    def test_all_deep_metrics_bounded(self):
        from ageval.metrics import list_metrics
        steps = [
            {"tool_name": "llm_call", "success": True, "latency_ms": None,
             "tool_output": {"input_tokens": 10, "output_tokens": 5}},
            {"tool_name": "a", "success": False, "latency_ms": 50, "error_category": "env_error"},
            {"tool_name": "a", "success": True, "latency_ms": 60},
        ]
        for m in list_metrics():
            v = get_metric(m["name"])(steps, {"total_steps": 3})
            assert 0.0 <= v <= 1.0, f"{m['name']}={v} out of range"
