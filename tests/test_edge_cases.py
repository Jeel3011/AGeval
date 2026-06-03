"""
tests/test_edge_cases.py

Explicit edge-case tests for the trickiest code paths — the ones property tests
don't naturally hit because they need specific, constructed scenarios:

  - /overview aggregation: empty, mixed scorers, non-numeric breakdown values
  - datasets: test-case insert failure rolls back the parent dataset row
  - red-team: a probe that errors mid-run counts as NOT bypassed
  - llm_judge: response parsing clamps, fills missing keys, rejects bad JSON
  - synthetic: extraction prefers known keys over arbitrary first-list
"""

from __future__ import annotations

import types

import pytest

import main
import api.datasets as datasets
from api.schemas import DatasetCreate, TestCase as _TC
from api.synthetic import _extract_array
from eval.llm_judge import _parse_response, METRIC_KEYS
from tests.fakes import FakeSupabase


# ---------------------------------------------------------------------------
# /overview aggregation
# ---------------------------------------------------------------------------
def test_overview_empty_user():
    db = FakeSupabase()
    main._supabase = db
    out = main.dashboard_overview(limit=200, user_id="nobody")
    assert out["total_episodes"] == 0
    assert out["scores"] == {}
    assert out["metric_breakdown"] == {}


def test_overview_ignores_non_numeric_breakdown_values():
    db = FakeSupabase()
    main._supabase = db
    db.seed("episodes", [
        {"episode_id": "e1", "agent_id": "a", "user_id": "u", "outcome": "success",
         "total_steps": 2, "total_latency_ms": 100, "created_at": "2026-06-01T00:00:00+00:00"},
    ])
    # llm_judge breakdowns carry non-numeric keys (judge_model, reasoning) — they
    # must NOT pollute the numeric average.
    db.seed("episode_scores", [
        {"episode_id": "e1", "scorer": "custom", "score": 0.8,
         "breakdown": {"success_rate": 1.0, "judge_model": "gpt-4o-mini", "reasoning": "ok"}},
    ])
    out = main.dashboard_overview(limit=200, user_id="u")
    assert out["metric_breakdown"] == {"success_rate": 1.0}
    assert out["scores"]["custom"] == 0.8


def test_overview_multiple_scorers_averaged_separately():
    db = FakeSupabase()
    main._supabase = db
    db.seed("episodes", [
        {"episode_id": f"e{i}", "agent_id": "a", "user_id": "u", "outcome": "success",
         "total_steps": 1, "total_latency_ms": 10, "created_at": f"2026-06-0{i+1}T00:00:00+00:00"}
        for i in range(2)
    ])
    db.seed("episode_scores", [
        {"episode_id": "e0", "scorer": "rules", "score": 0.6, "breakdown": {}},
        {"episode_id": "e1", "scorer": "rules", "score": 0.8, "breakdown": {}},
        {"episode_id": "e0", "scorer": "llm_judge", "score": 1.0, "breakdown": {}},
    ])
    out = main.dashboard_overview(limit=200, user_id="u")
    assert out["scores"]["rules"] == 0.7          # (0.6 + 0.8) / 2
    assert out["scores"]["llm_judge"] == 1.0


# ---------------------------------------------------------------------------
# datasets rollback
# ---------------------------------------------------------------------------
def test_dataset_rolls_back_on_test_case_failure(monkeypatch):
    db = FakeSupabase()

    # Make ONLY the dataset_test_cases insert explode.
    real_table = db.table

    def patched_table(name):
        q = real_table(name)
        if name == "dataset_test_cases":
            def boom(_payload):
                raise RuntimeError("insert failed")
            q.insert = boom  # type: ignore[assignment]
        return q

    monkeypatch.setattr(datasets, "_db", lambda: types.SimpleNamespace(table=patched_table))

    payload = DatasetCreate(
        project_id="p", name="X", version="v1",
        test_cases=[_TC(input_data={"q": "a"}, expected_output="b")],
    )
    with pytest.raises(Exception):
        datasets.create_dataset(payload, user_id="u")

    # The parent dataset row must have been rolled back (deleted).
    remaining = db.table("golden_datasets").select("*").eq("user_id", "u").execute()
    assert remaining.data == []


# ---------------------------------------------------------------------------
# red-team: error during a probe is not a bypass
# ---------------------------------------------------------------------------
def test_redteam_probe_error_is_not_a_bypass(monkeypatch):
    import sys
    from api.redteam_engine import run_red_team

    class _Boom:
        def __init__(self, **k):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._c)
            )

        def _c(self, **kwargs):
            raise RuntimeError("api down")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda api_key=None: _Boom()))

    card = run_red_team(model="gpt-4o-mini")
    # Every probe errored → zero bypasses → grade A (errors are conservative).
    assert card["bypasses"] == 0
    assert card["overall_grade"] == "A"


# ---------------------------------------------------------------------------
# llm_judge response parsing
# ---------------------------------------------------------------------------
def test_judge_parse_clamps_and_fills_missing():
    raw = '{"scores": {"task_completion": 2.5, "reasoning_quality": -1}, "reasoning": "x"}'
    parsed = _parse_response(raw)
    assert parsed["scores"]["task_completion"] == 1.0   # clamped from 2.5
    assert parsed["scores"]["reasoning_quality"] == 0.0  # clamped from -1
    # Missing dimensions default to 0.0 (e.g. our new hallucination_free key).
    for k in METRIC_KEYS:
        assert 0.0 <= parsed["scores"][k] <= 1.0


def test_judge_parse_rejects_bad_json():
    with pytest.raises(RuntimeError):
        _parse_response("not json at all")


# ---------------------------------------------------------------------------
# synthetic extraction priority
# ---------------------------------------------------------------------------
def test_extract_prefers_known_key_over_arbitrary_list():
    parsed = {"metadata": ["junk"], "examples": [{"good": 1}]}
    assert _extract_array(parsed) == [{"good": 1}]
