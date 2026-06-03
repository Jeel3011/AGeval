"""
tests/test_phase3_eval.py

Tests for Phase-3 features (EVAL_DEPTH_AND_MEMORY_PLAN §2.4, §2.5, §2.6):

  • pairwise / A-B trajectory comparison  (eval/pairwise.py)
  • online drift detection                (merger/drift.py)
  • reference-grounded metrics            (eval/reference.py)

Pure logic is tested directly; DB-backed paths run against the in-memory fake.
LLM calls are monkeypatched off so everything is deterministic and offline.
"""

from __future__ import annotations

from eval.pairwise import _seq_diff, compare_episodes, compare_trajectories
from eval.reference import _final_output_text, score_reference_metrics
from merger.drift import detect_drift, run_drift_alerts
from tests.fakes import FakeSupabase


def _step(ep, idx, tool, success=True):
    return {"episode_id": ep, "step_index": idx, "tool_name": tool, "success": success}


# ---------------------------------------------------------------------------
# §2.4 — pairwise comparison
# ---------------------------------------------------------------------------
def test_seq_diff_alignment():
    ops = _seq_diff(["a", "b", "c"], ["a", "x", "c"])
    kinds = [(o["op"], o["tool"]) for o in ops]
    assert ("same", "a") in kinds
    assert ("same", "c") in kinds
    assert ("a_only", "b") in kinds
    assert ("b_only", "x") in kinds


def test_compare_trajectories_score_and_step_deltas():
    ep_a = {
        "episode_id": "a", "outcome": "success",
        "steps": [_step("a", 0, "search"), _step("a", 1, "fetch")],
        "scores": {"rules": 0.8},
    }
    ep_b = {
        "episode_id": "b", "outcome": "failure",
        "steps": [_step("b", 0, "search"), _step("b", 1, "fetch"), _step("b", 2, "retry")],
        "scores": {"rules": 0.5},
    }
    out = compare_trajectories(ep_a, ep_b)
    assert out["step_delta"] == 1
    assert out["score_deltas"]["rules"]["delta"] == -0.3
    assert out["edit_distance"] == 1


def test_compare_episodes_db(monkeypatch):
    monkeypatch.setattr("eval.pairwise._llm_pairwise", lambda a, b: None)
    db = FakeSupabase()
    db.seed("episodes", [
        {"episode_id": "a", "user_id": "u", "task": "t", "outcome": "success", "final_output": {}},
        {"episode_id": "b", "user_id": "u", "task": "t", "outcome": "failure", "final_output": {}},
    ])
    db.seed("episode_steps", [_step("a", 0, "search"), _step("b", 0, "search"), _step("b", 1, "retry")])
    db.seed("episode_scores", [
        {"episode_id": "a", "scorer": "rules", "score": 0.9},
        {"episode_id": "b", "scorer": "rules", "score": 0.4},
    ])
    out = compare_episodes(db, "u", "a", "b", use_llm=True)
    assert out["a"]["episode_id"] == "a"
    assert out["score_deltas"]["rules"]["delta"] == -0.5
    assert "llm_verdict" not in out  # monkeypatched off


def test_compare_episodes_rejects_foreign(monkeypatch):
    monkeypatch.setattr("eval.pairwise._llm_pairwise", lambda a, b: None)
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "a", "user_id": "u", "outcome": "success"}])
    import pytest
    with pytest.raises(ValueError):
        compare_episodes(db, "other", "a", "a")


# ---------------------------------------------------------------------------
# §2.6 — drift detection
# ---------------------------------------------------------------------------
def test_detect_drift_fires_below_threshold():
    # baseline 0.8 ± 0.05, recent mean 0.6 → 0.8 - 2*0.05 = 0.7, 0.6 < 0.7 → drift
    d = detect_drift(0.8, 0.05, [0.6, 0.6, 0.6, 0.6, 0.6])
    assert d is not None
    assert d["recent_mean"] == 0.6
    assert d["drop"] == 0.2


def test_detect_drift_silent_when_stable():
    assert detect_drift(0.8, 0.1, [0.78, 0.82, 0.79, 0.81, 0.80]) is None


def test_detect_drift_needs_min_recent():
    assert detect_drift(0.8, 0.05, [0.1, 0.1]) is None  # below MIN_RECENT


def test_run_drift_alerts_records(monkeypatch):
    db = FakeSupabase()
    db.seed("cluster_baselines", [
        {"cluster_id": "c1", "scorer": "custom", "mean": 0.9, "stddev": 0.05},
    ])
    db.seed("episodes", [
        {"episode_id": f"e{i}", "cluster_id": "c1", "created_at": "2999-01-01T00:00:00+00:00"}
        for i in range(6)
    ])
    db.seed("episode_scores", [
        {"episode_id": f"e{i}", "scorer": "custom", "score": 0.5} for i in range(6)
    ])
    found = run_drift_alerts(db, scorer="custom")
    assert found == 1
    assert len(db._tables["drift_alerts"]) == 1


# ---------------------------------------------------------------------------
# §2.5 — reference-grounded metrics
# ---------------------------------------------------------------------------
def test_final_output_text_extraction():
    assert _final_output_text({"final_output": {"answer": "hi"}}) == "hi"
    assert _final_output_text({"final_output": "plain"}) == "plain"
    assert _final_output_text({"final_output": None}) == ""


def test_score_reference_metrics(monkeypatch):
    monkeypatch.setattr("ageval.llm_metrics.evaluate_answer_relevance",
                        lambda i, o: {"score": 0.9, "reasoning": "direct"})
    monkeypatch.setattr("ageval.llm_metrics.evaluate_faithfulness",
                        lambda i, o, c: {"score": 0.7, "reasoning": "mostly grounded"})
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "e1", "task": "answer X", "final_output": {"answer": "X is 42"}}])

    out = score_reference_metrics(db, "e1", context=["X is 42"])
    assert out["breakdown"]["answer_relevance"] == 0.9
    assert out["breakdown"]["faithfulness"] == 0.7
    assert out["score"] == 0.8
    rows = db.table("episode_scores").select("*").eq("episode_id", "e1").execute()
    assert rows.data[0]["scorer"] == "reference"


def test_score_reference_metrics_none_without_output():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "e1", "task": "x", "final_output": None}])
    assert score_reference_metrics(db, "e1") is None
