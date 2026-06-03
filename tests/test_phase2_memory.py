"""
tests/test_phase2_memory.py

Tests for Phase-2 evaluation-memory features
(EVAL_DEPTH_AND_MEMORY_PLAN §1.3 + §2.1):

  • procedural memory mining   (merger/procedural.py)
  • trajectory_adherence       (eval/trajectory.py)
  • regression detection       (api/regression.py)

All run against the in-memory FakeSupabase — no live Postgres, no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.regression import compute_regression, default_window, fetch_and_compute
from eval.trajectory import adherence, levenshtein, score_trajectory_adherence
from merger.procedural import (
    _median,
    _select_exemplars,
    mine_golden_trajectory,
)
from tests.fakes import FakeSupabase


def _step(ep, idx, tool, success=True):
    return {"episode_id": ep, "step_index": idx, "tool_name": tool, "success": success}


# ---------------------------------------------------------------------------
# §1.3 — procedural memory
# ---------------------------------------------------------------------------
def test_median():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, 4]) == 2.5
    assert _median([]) == 0.0


def test_select_exemplars_prefers_top_successful():
    scored = [
        {"episode_id": "e1", "score": 0.9, "outcome": "success"},
        {"episode_id": "e2", "score": 0.8, "outcome": "success"},
        {"episode_id": "e3", "score": 0.7, "outcome": "success"},
        {"episode_id": "e4", "score": 0.2, "outcome": "failure"},
    ]
    ex = _select_exemplars(scored)
    ids = {e["episode_id"] for e in ex}
    assert "e4" not in ids  # failures excluded when successes exist
    assert "e1" in ids       # top score kept


def test_select_exemplars_needs_minimum():
    scored = [{"episode_id": "e1", "score": 0.9, "outcome": "success"}]
    assert _select_exemplars(scored) == []


def test_mine_golden_trajectory_picks_modal_sequence():
    db = FakeSupabase()
    # 4 successful episodes; 3 share the path [search, fetch, summarize].
    eps = ["e1", "e2", "e3", "e4"]
    db.seed("episodes", [{"episode_id": e, "outcome": "success"} for e in eps])
    db.seed("episode_scores", [{"episode_id": e, "scorer": "custom", "score": 0.9} for e in eps])
    for e in ("e1", "e2", "e3"):
        db.seed("episode_steps", [
            _step(e, 0, "search"), _step(e, 1, "fetch"), _step(e, 2, "summarize"),
        ])
    db.seed("episode_steps", [_step("e4", 0, "search"), _step("e4", 1, "guess")])

    assert mine_golden_trajectory(db, "c1", "userX", "agentA", eps) is True
    pm = db._tables["procedural_memory"]
    assert len(pm) == 1
    assert pm[0]["golden_sequence"] == ["search", "fetch", "summarize"]
    assert pm[0]["cluster_id"] == "c1"
    assert "search" in pm[0]["expected_tools"]


def test_mine_golden_trajectory_skips_when_too_few():
    db = FakeSupabase()
    eps = ["e1", "e2"]
    db.seed("episodes", [{"episode_id": e, "outcome": "success"} for e in eps])
    db.seed("episode_scores", [{"episode_id": e, "scorer": "custom", "score": 0.9} for e in eps])
    for e in eps:
        db.seed("episode_steps", [_step(e, 0, "search")])
    assert mine_golden_trajectory(db, "c1", "userX", "agentA", eps) is False
    assert db._tables.get("procedural_memory", []) == []


# ---------------------------------------------------------------------------
# §1.3 — trajectory adherence
# ---------------------------------------------------------------------------
def test_levenshtein_basics():
    assert levenshtein([], []) == 0
    assert levenshtein(["a"], []) == 1
    assert levenshtein(["a", "b", "c"], ["a", "x", "c"]) == 1


def test_adherence_identical_and_disjoint():
    assert adherence(["a", "b"], ["a", "b"]) == 1.0
    assert adherence([], []) == 1.0
    assert adherence(["a", "b"], ["x", "y"]) == 0.0
    # one substitution out of two → 0.5
    assert adherence(["a", "b"], ["a", "x"]) == 0.5


def test_score_trajectory_adherence_persists():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "e1", "cluster_id": "c1"}])
    db.seed("procedural_memory", [{
        "cluster_id": "c1",
        "golden_sequence": ["search", "fetch", "summarize"],
        "expected_steps": 3, "n": 5,
    }])
    db.seed("episode_steps", [
        _step("e1", 0, "search"), _step("e1", 1, "fetch"), _step("e1", 2, "summarize"),
    ])
    result = score_trajectory_adherence(db, "e1")
    assert result is not None
    assert result["score"] == 1.0
    rows = db.table("episode_scores").select("*").eq("episode_id", "e1").execute()
    assert rows.data[0]["scorer"] == "trajectory"
    assert rows.data[0]["score"] == 1.0


def test_score_trajectory_adherence_none_without_golden_path():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "e1", "cluster_id": None}])
    assert score_trajectory_adherence(db, "e1") is None


# ---------------------------------------------------------------------------
# §2.1 — regression detection
# ---------------------------------------------------------------------------
def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_default_window_is_7_vs_prior_7():
    f, t = default_window()
    assert (t - f).days == 7


def test_compute_regression_flags_score_drop_and_new_failures():
    from_ts = datetime.now(timezone.utc) - timedelta(days=14)
    to_ts = datetime.now(timezone.utc) - timedelta(days=7)

    episodes = [
        # baseline cohort (older)
        {"episode_id": "b1", "created_at": _iso(10), "outcome": "success",
         "total_steps": 3, "episode_fingerprint": "fp_old"},
        {"episode_id": "b2", "created_at": _iso(9), "outcome": "success",
         "total_steps": 3, "episode_fingerprint": "fp_old"},
        # after cohort (recent)
        {"episode_id": "a1", "created_at": _iso(2), "outcome": "failure",
         "total_steps": 6, "episode_fingerprint": "fp_new"},
        {"episode_id": "a2", "created_at": _iso(1), "outcome": "failure",
         "total_steps": 6, "episode_fingerprint": "fp_old"},
    ]
    scores = {
        "b1": {"rules": 0.9}, "b2": {"rules": 0.9},
        "a1": {"rules": 0.4}, "a2": {"rules": 0.4},
    }
    failures = {"baseline": set(), "after": {"env_error|inventory|late"}}

    out = compute_regression(episodes, scores, failures, from_ts, to_ts)

    assert out["window"]["baseline_n"] == 2
    assert out["window"]["after_n"] == 2
    assert out["score_deltas"]["rules"]["delta"] == -0.5
    assert out["step_drift"]["baseline"] == 3.0
    assert out["step_drift"]["after"] == 6.0
    assert out["new_failures"] == ["env_error|inventory|late"]
    assert out["new_trajectories"] == ["fp_new"]
    assert out["regressed"] is True


def test_compute_regression_stable_when_no_change():
    from_ts = datetime.now(timezone.utc) - timedelta(days=14)
    to_ts = datetime.now(timezone.utc) - timedelta(days=7)
    episodes = [
        {"episode_id": "b1", "created_at": _iso(10), "outcome": "success",
         "total_steps": 3, "episode_fingerprint": "fp"},
        {"episode_id": "a1", "created_at": _iso(2), "outcome": "success",
         "total_steps": 3, "episode_fingerprint": "fp"},
    ]
    scores = {"b1": {"rules": 0.8}, "a1": {"rules": 0.82}}
    out = compute_regression(episodes, scores, {"baseline": set(), "after": set()}, from_ts, to_ts)
    assert out["regressed"] is False
    assert out["new_trajectories"] == []


def test_fetch_and_compute_end_to_end(monkeypatch):
    db = FakeSupabase()
    db.seed("episodes", [
        {"episode_id": "b1", "user_id": "u", "agent_id": "A", "created_at": _iso(10),
         "outcome": "success", "total_steps": 3, "episode_fingerprint": "fp_old"},
        {"episode_id": "a1", "user_id": "u", "agent_id": "A", "created_at": _iso(2),
         "outcome": "failure", "total_steps": 7, "episode_fingerprint": "fp_new"},
        # other agent / other user must be excluded
        {"episode_id": "x1", "user_id": "u", "agent_id": "B", "created_at": _iso(2),
         "outcome": "failure", "total_steps": 9, "episode_fingerprint": "fp_x"},
    ])
    db.seed("episode_scores", [
        {"episode_id": "b1", "scorer": "rules", "score": 0.9},
        {"episode_id": "a1", "scorer": "rules", "score": 0.3},
    ])
    # A new failure signature only in the recent window.
    fid = db.table("failure_memory").insert({
        "id": "f1", "user_id": "u", "agent_id": "A",
        "signature": "env_error|pay|late", "occurrences": 1,
    }).execute().data[0]["id"]
    db.seed("failure_occurrences", [{"failure_id": fid, "episode_id": "a1"}])

    out = fetch_and_compute(db, "u", "A", None, None)
    assert out["window"]["baseline_n"] == 1
    assert out["window"]["after_n"] == 1
    assert out["score_deltas"]["rules"]["delta"] == -0.6
    assert out["new_failures"] == ["env_error|pay|late"]
    assert out["new_trajectories"] == ["fp_new"]
    assert out["regressed"] is True
