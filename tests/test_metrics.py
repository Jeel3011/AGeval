"""
tests/test_metrics.py

Tests for the custom metric registry.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
