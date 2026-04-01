"""
tests/test_eval_rules.py

Pure unit tests for eval/rules.py metric functions.
No Supabase / LangSmith / network required — everything is mocked.

Run with:
    pytest tests/test_eval_rules.py -v
"""

import pytest
from eval.rules import (
    calc_success_rate,
    calc_recovery_rate,
    calc_reasoning_coverage,
    calc_efficiency_score,
    score_episode,
    _resolve_weights,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def make_step(step_index, tool_name, success, error_category=None, reasoning=None, latency_ms=100):
    return {
        "step_index"    : step_index,
        "tool_name"     : tool_name,
        "success"       : success,
        "error_category": error_category,
        "reasoning"     : reasoning,
        "latency_ms"    : latency_ms,
    }


# ---------------------------------------------------------------------------
# calc_success_rate
# ---------------------------------------------------------------------------
class TestSuccessRate:
    def test_all_succeed(self):
        steps = [make_step(i, "tool", True) for i in range(3)]
        assert calc_success_rate(steps) == 1.0

    def test_all_fail(self):
        steps = [make_step(i, "tool", False) for i in range(3)]
        assert calc_success_rate(steps) == 0.0

    def test_partial(self):
        steps = [
            make_step(0, "tool", True),
            make_step(1, "tool", False),
            make_step(2, "tool", True),
            make_step(3, "tool", True),
        ]
        assert calc_success_rate(steps) == 0.75

    def test_single_step_success(self):
        assert calc_success_rate([make_step(0, "tool", True)]) == 1.0

    def test_single_step_fail(self):
        assert calc_success_rate([make_step(0, "tool", False)]) == 0.0


# ---------------------------------------------------------------------------
# calc_recovery_rate
# ---------------------------------------------------------------------------
class TestRecoveryRate:
    def test_no_env_errors(self):
        steps = [make_step(0, "tool", True)]
        assert calc_recovery_rate(steps) == 1.0

    def test_env_error_recovered(self):
        steps = [
            make_step(0, "search", False, error_category="env_error"),
            make_step(1, "search", True),
        ]
        assert calc_recovery_rate(steps) == 1.0

    def test_env_error_not_recovered(self):
        steps = [
            make_step(0, "search", False, error_category="env_error"),
            make_step(1, "parse", False, error_category="agent_error"),
        ]
        assert calc_recovery_rate(steps) == 0.0

    def test_multiple_env_errors_one_recovered(self):
        steps = [
            make_step(0, "fetch", False, error_category="env_error"),
            make_step(1, "fetch", True),                                  # recovered
            make_step(2, "parse", False, error_category="env_error"),
            make_step(3, "parse", False, error_category="agent_error"),   # not recovered (agent, not success)
        ]
        assert calc_recovery_rate(steps) == 0.5

    def test_agent_error_not_counted(self):
        steps = [
            make_step(0, "tool", False, error_category="agent_error"),
            make_step(1, "tool", True),
        ]
        # agent_errors are NOT counted — no env_errors → full marks
        assert calc_recovery_rate(steps) == 1.0


# ---------------------------------------------------------------------------
# calc_reasoning_coverage
# ---------------------------------------------------------------------------
class TestReasoningCoverage:
    def test_all_have_reasoning(self):
        steps = [make_step(i, "tool", True, reasoning="think") for i in range(3)]
        assert calc_reasoning_coverage(steps) == 1.0

    def test_none_have_reasoning(self):
        steps = [make_step(i, "tool", True, reasoning=None) for i in range(3)]
        assert calc_reasoning_coverage(steps) == 0.0

    def test_empty_string_not_counted(self):
        steps = [make_step(i, "tool", True, reasoning="") for i in range(3)]
        assert calc_reasoning_coverage(steps) == 0.0

    def test_whitespace_not_counted(self):
        steps = [make_step(i, "tool", True, reasoning="   ") for i in range(3)]
        assert calc_reasoning_coverage(steps) == 0.0

    def test_partial(self):
        steps = [
            make_step(0, "tool", True,  reasoning="think"),
            make_step(1, "tool", False, reasoning=None),
            make_step(2, "tool", True,  reasoning="reason"),
        ]
        assert calc_reasoning_coverage(steps) == round(2 / 3, 4)


# ---------------------------------------------------------------------------
# calc_efficiency_score
# ---------------------------------------------------------------------------
class TestEfficiencyScore:
    def test_one_step(self):
        assert calc_efficiency_score([make_step(0, "tool", True)]) == 1.0

    def test_no_duplicates(self):
        steps = [
            make_step(0, "search", True),
            make_step(1, "parse",  True),
            make_step(2, "report", True),
        ]
        assert calc_efficiency_score(steps) == 1.0

    def test_all_duplicates(self):
        steps = [make_step(i, "search", True) for i in range(4)]
        # 3 consecutive duplicate pairs out of 3 possible → 0.0
        assert calc_efficiency_score(steps) == 0.0

    def test_partial(self):
        steps = [
            make_step(0, "search", False),   # pair 0→1: duplicate
            make_step(1, "search", True),    # pair 1→2: not duplicate
            make_step(2, "parse",  True),    # pair 2→3: not duplicate
            make_step(3, "report", True),
        ]
        # 1 duplicate / 3 pairs = penalty of 1/3 → efficiency = 1 - 1/3 ≈ 0.6667
        assert calc_efficiency_score(steps) == round(1 - 1/3, 4)

    def test_unsorted_input_handled(self):
        """Steps out of order should still be evaluated by step_index."""
        steps = [
            make_step(2, "parse",  True),
            make_step(0, "search", True),
            make_step(1, "search", True),  # duplicate of step 0
        ]
        # After sorting: search → search → parse → 1 duplicate in 2 pairs
        assert calc_efficiency_score(steps) == 0.5


# ---------------------------------------------------------------------------
# _resolve_weights
# ---------------------------------------------------------------------------
class TestResolveWeights:
    def test_defaults_returned_when_none(self):
        w = _resolve_weights(None)
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert "success_rate" in w

    def test_valid_custom_weights(self):
        w = _resolve_weights({
            "success_rate"      : 0.4,
            "recovery_rate"     : 0.3,
            "reasoning_coverage": 0.15,
            "efficiency_score"  : 0.15,
        })
        assert w["success_rate"] == 0.4

    def test_weights_not_summing_to_one(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            _resolve_weights({
                "success_rate"      : 0.5,
                "recovery_rate"     : 0.5,
                "reasoning_coverage": 0.5,
                "efficiency_score"  : 0.5,
            })

    def test_unknown_metric_key(self):
        with pytest.raises(ValueError, match="Unknown metric keys"):
            _resolve_weights({
                "success_rate"      : 0.25,
                "recovery_rate"     : 0.25,
                "reasoning_coverage": 0.25,
                "fake_metric"       : 0.25,
            })

    def test_missing_metric_key(self):
        with pytest.raises(ValueError, match="Missing metric keys"):
            _resolve_weights({
                "success_rate"  : 0.5,
                "recovery_rate" : 0.5,
            })


# ---------------------------------------------------------------------------
# score_episode (mocked client)
# ---------------------------------------------------------------------------
class MockSupabaseClient:
    """Minimal mock of supabase client for unit testing without network."""

    def __init__(self, steps: list[dict]):
        self._steps       = steps
        self.upserted     = []

    def table(self, name: str):
        return _MockTable(name, self)


class _MockTable:
    def __init__(self, name: str, client):
        self._name   = name
        self._client = client
        self._query  = None

    def select(self, *a, **kw):   return self
    def eq(self, *a, **kw):       return self
    def order(self, *a, **kw):    return self
    def upsert(self, d, **kw):
        self._client.upserted.append(d)
        return self

    def execute(self):
        if self._name == "episode_steps":
            return _MockResult(self._client._steps)
        if self._name == "episode_scores":
            return _MockResult([])
        return _MockResult([])


class _MockResult:
    def __init__(self, data):
        self.data = data


class TestScoreEpisode:
    def _steps(self):
        return [
            make_step(0, "search", False, "env_error",  "retry search"),  # env_error
            make_step(1, "search", True,  None,          "retrying now"),  # recovered
            make_step(2, "parse",  True,  None,          None),            # no reasoning
            make_step(3, "report", False, "agent_error", "bad input"),     # agent_error
            make_step(4, "parse",  False, "agent_error", None),            # consecutive dup
        ]

    def test_returns_expected_keys(self):
        client = MockSupabaseClient(self._steps())
        result = score_episode(client, "ep_test_abc")
        assert "episode_id"  in result
        assert "score"       in result
        assert "breakdown"   in result
        assert "weights_used" in result
        assert result["scorer"] == "rules"

    def test_score_is_0_to_1(self):
        client = MockSupabaseClient(self._steps())
        result = score_episode(client, "ep_test_abc")
        assert 0.0 <= result["score"] <= 1.0

    def test_score_written_to_db(self):
        client = MockSupabaseClient(self._steps())
        score_episode(client, "ep_test_abc")
        assert len(client.upserted) == 1
        assert client.upserted[0]["scorer"] == "rules"

    def test_custom_weights_applied(self):
        client_a = MockSupabaseClient(self._steps())
        client_b = MockSupabaseClient(self._steps())
        result_equal = score_episode(client_a, "ep_a")
        result_skewed = score_episode(client_b, "ep_b", weights={
            "success_rate"      : 0.9,
            "recovery_rate"     : 0.033,
            "reasoning_coverage": 0.033,
            "efficiency_score"  : 0.034,
        })
        # Different weights → different scores
        assert result_equal["score"] != result_skewed["score"]

    def test_raises_on_empty_steps(self):
        client = MockSupabaseClient([])
        with pytest.raises(ValueError, match="No steps found"):
            score_episode(client, "ep_empty")
