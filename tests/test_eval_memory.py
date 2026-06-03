"""
tests/test_eval_memory.py

Tests for Phase-1 evaluation-memory features
(EVAL_DEPTH_AND_MEMORY_PLAN §1.1, §1.2, §1.4, §2.2, §2.3):

  • episode fingerprinting          (merger/fingerprint.py)
  • failure-pattern memory mining   (merger/failure_memory.py)
  • cluster score baselines         (merger/baselines.py)
  • peer-relative scoring           (eval/relative.py)

All run against the in-memory FakeSupabase — no live Postgres, no network.
Embedding generation is monkeypatched off so failure_memory exercises its
no-embedding path deterministically.
"""

from __future__ import annotations

import pytest

from eval.relative import _band, _percentile_of, relative_scores
from merger.baselines import MIN_BASELINE_N, _distribution, _percentile, compute_baselines
from merger.failure_memory import (
    _merge_centroid,
    _position_band,
    _signature,
    record_failures,
)
from merger.fingerprint import compute_fingerprint, tool_sequence
from tests.fakes import FakeSupabase


# ---------------------------------------------------------------------------
# §1.1 — fingerprinting
# ---------------------------------------------------------------------------
def _step(idx, tool, success=True, cat=None, msg=None):
    return {
        "step_index": idx,
        "tool_name": tool,
        "success": success,
        "error_category": cat,
        "error_message": msg,
    }


def test_fingerprint_is_stable_and_shape_sensitive():
    steps = [_step(0, "search"), _step(1, "fetch"), _step(2, "summarize")]
    fp = compute_fingerprint(steps, "success")
    # Stable across calls.
    assert fp == compute_fingerprint(steps, "success")
    # 16 hex chars.
    assert len(fp) == 16 and all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_same_shape_same_hash_regardless_of_args_or_latency():
    a = [_step(0, "search"), _step(1, "fetch")]
    b = [
        {"step_index": 0, "tool_name": "search", "success": True, "latency_ms": 999, "tool_input": {"q": "x"}},
        {"step_index": 1, "tool_name": "fetch", "success": True, "latency_ms": 1, "reasoning": "because"},
    ]
    assert compute_fingerprint(a, "success") == compute_fingerprint(b, "success")


def test_fingerprint_differs_on_outcome_and_order():
    steps = [_step(0, "search"), _step(1, "fetch")]
    assert compute_fingerprint(steps, "success") != compute_fingerprint(steps, "failure")
    reordered = [_step(0, "fetch"), _step(1, "search")]
    assert compute_fingerprint(steps, "success") != compute_fingerprint(reordered, "success")


def test_fingerprint_excludes_llm_call_bookkeeping():
    with_llm = [_step(0, "llm_call"), _step(1, "search"), _step(2, "llm_call")]
    without = [_step(0, "search")]
    assert tool_sequence(with_llm) == ["search"]
    assert compute_fingerprint(with_llm, "success") == compute_fingerprint(without, "success")


def test_fingerprint_empty_episode_is_deterministic():
    assert compute_fingerprint([], "failure") == compute_fingerprint([], "failure")


# ---------------------------------------------------------------------------
# §1.4 — failure-pattern memory
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_embeddings(monkeypatch):
    # Keep failure_memory deterministic & offline: no embedding centroid.
    monkeypatch.setattr("merger.merger.generate_embedding", lambda _t: None)


def test_position_band_buckets():
    assert _position_band(0, 9) == "early"
    assert _position_band(4, 9) == "mid"
    assert _position_band(8, 9) == "late"
    assert _position_band(0, 1) == "early"  # single-step edge case


def test_signature_format():
    assert _signature("env_error", "inventory", "late") == "env_error|inventory|late"
    assert _signature(None, None, "early") == "unknown|?|early"


def test_record_failures_creates_signature_and_occurrence():
    db = FakeSupabase()
    steps = [
        _step(0, "search", success=True),
        _step(1, "inventory", success=False, cat="env_error", msg="timeout"),
    ]
    matched = record_failures(db, "ep1", "agentA", "userX", steps)

    assert len(matched) == 1
    fm = db._tables["failure_memory"]
    assert len(fm) == 1
    assert fm[0]["occurrences"] == 1
    assert fm[0]["agent_id"] == "agentA"
    assert fm[0]["user_id"] == "userX"
    assert fm[0]["sample_episode_id"] == "ep1"
    occ = db._tables["failure_occurrences"]
    assert len(occ) == 1 and occ[0]["episode_id"] == "ep1"


def test_record_failures_increments_recurrence_across_episodes():
    db = FakeSupabase()

    def failing(ep):
        return record_failures(
            db, ep, "agentA", "userX",
            [_step(1, "inventory", success=False, cat="env_error", msg="timeout")],
        )

    failing("ep1")
    failing("ep2")
    failing("ep3")

    fm = db._tables["failure_memory"]
    assert len(fm) == 1  # same signature → one row
    assert fm[0]["occurrences"] == 3
    assert len(db._tables["failure_occurrences"]) == 3


def test_record_failures_ignores_clean_runs_and_llm_calls():
    db = FakeSupabase()
    steps = [_step(0, "llm_call", success=False, cat="agent_error"), _step(1, "search", success=True)]
    # llm_call failures are bookkeeping; the real tool succeeded → no signature.
    assert record_failures(db, "ep1", "agentA", "userX", steps) == []
    assert db._tables.get("failure_memory", []) == []


def test_record_failures_needs_user_id():
    db = FakeSupabase()
    steps = [_step(1, "inventory", success=False, cat="env_error")]
    assert record_failures(db, "ep1", "agentA", None, steps) == []


def test_record_failures_collapses_duplicate_signature_within_one_episode():
    db = FakeSupabase()
    # Same tool/category fall in the same position band (both early in a long
    # run) → one signature → counts once for this episode.
    steps = [
        _step(0, "inventory", success=False, cat="env_error", msg="t1"),
        _step(1, "inventory", success=False, cat="env_error", msg="t2"),
    ] + [_step(i, "noop", success=True) for i in range(2, 12)]
    matched = record_failures(db, "ep1", "agentA", "userX", steps)
    assert matched == ["env_error|inventory|early"]
    assert db._tables["failure_memory"][0]["occurrences"] == 1


def test_merge_centroid_running_mean():
    assert _merge_centroid(None, 0, [1.0, 1.0]) == [1.0, 1.0]
    # mean of [0,0] (n=1) and [2,2] → [1,1]
    assert _merge_centroid([0.0, 0.0], 1, [2.0, 2.0]) == [1.0, 1.0]
    # new is None → keep old
    assert _merge_centroid([0.5], 3, None) == [0.5]


# ---------------------------------------------------------------------------
# §1.2 — cluster baselines
# ---------------------------------------------------------------------------
def test_percentile_interpolation():
    vals = [0.0, 0.5, 1.0]
    assert _percentile(vals, 0) == 0.0
    assert _percentile(vals, 50) == 0.5
    assert _percentile(vals, 100) == 1.0


def test_distribution_basic_stats():
    d = _distribution([0.0, 0.0, 1.0, 1.0])
    assert d["n"] == 4
    assert d["mean"] == 0.5
    assert d["stddev"] == 0.5


def test_compute_baselines_respects_cold_start_gate():
    db = FakeSupabase()
    ep_ids = [f"ep{i}" for i in range(MIN_BASELINE_N - 1)]
    db.seed("episode_scores", [
        {"episode_id": e, "scorer": "rules", "score": 0.8} for e in ep_ids
    ])
    # Below the gate → nothing persisted.
    assert compute_baselines(db, "cluster1", ep_ids) == 0
    assert db._tables.get("cluster_baselines", []) == []


def test_compute_baselines_writes_above_gate():
    db = FakeSupabase()
    ep_ids = [f"ep{i}" for i in range(MIN_BASELINE_N)]
    db.seed("episode_scores", [
        {"episode_id": e, "scorer": "rules", "score": 0.6} for e in ep_ids
    ] + [
        {"episode_id": e, "scorer": "custom", "score": 0.9} for e in ep_ids
    ])
    written = compute_baselines(db, "cluster1", ep_ids)
    assert written == 2
    rows = {r["scorer"]: r for r in db._tables["cluster_baselines"]}
    assert rows["rules"]["mean"] == 0.6
    assert rows["rules"]["n"] == MIN_BASELINE_N
    assert rows["custom"]["mean"] == 0.9


def test_compute_baselines_upserts_not_duplicates():
    db = FakeSupabase()
    ep_ids = [f"ep{i}" for i in range(MIN_BASELINE_N)]
    db.seed("episode_scores", [
        {"episode_id": e, "scorer": "rules", "score": 0.5} for e in ep_ids
    ])
    compute_baselines(db, "cluster1", ep_ids)
    compute_baselines(db, "cluster1", ep_ids)
    rows = [r for r in db._tables["cluster_baselines"] if r["cluster_id"] == "cluster1"]
    assert len(rows) == 1  # composite (cluster_id, scorer) upsert


# ---------------------------------------------------------------------------
# §2.3 — peer-relative scoring
# ---------------------------------------------------------------------------
def test_percentile_of_uses_quantiles():
    baseline = {"p10": 0.2, "p50": 0.5, "p90": 0.8, "mean": 0.5, "stddev": 0.2}
    assert _percentile_of(0.5, baseline) == pytest.approx(50.0, abs=1.0)
    assert _percentile_of(0.2, baseline) <= 12.0
    assert _percentile_of(0.8, baseline) >= 88.0


def test_band_labels():
    assert _band(5) == "bottom 10% of runs like it"
    assert _band(50) == "typical"
    assert _band(95) == "top 10% of runs like it"


def test_relative_scores_empty_when_unclustered():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "ep1", "cluster_id": None}])
    assert relative_scores(db, "ep1") == {}


def test_relative_scores_annotates_against_baseline():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "ep1", "cluster_id": "c1"}])
    db.seed("episode_scores", [{"episode_id": "ep1", "scorer": "rules", "score": 0.2}])
    db.seed("cluster_baselines", [{
        "cluster_id": "c1", "scorer": "rules", "n": 50,
        "mean": 0.6, "p10": 0.4, "p50": 0.6, "p90": 0.8, "stddev": 0.15,
    }])
    rel = relative_scores(db, "ep1")
    assert "rules" in rel
    # A 0.2 score against a cluster whose p10 is 0.4 → bottom band.
    assert rel["rules"]["percentile"] < 10
    assert rel["rules"]["band"] == "bottom 10% of runs like it"
    assert 0.0 < rel["rules"]["confidence"] <= 1.0
    assert rel["rules"]["baseline"]["n"] == 50


def test_relative_scores_skips_scorer_without_baseline():
    db = FakeSupabase()
    db.seed("episodes", [{"episode_id": "ep1", "cluster_id": "c1"}])
    db.seed("episode_scores", [
        {"episode_id": "ep1", "scorer": "rules", "score": 0.5},
        {"episode_id": "ep1", "scorer": "llm_judge", "score": 0.5},
    ])
    db.seed("cluster_baselines", [{
        "cluster_id": "c1", "scorer": "rules", "n": 30,
        "mean": 0.5, "p10": 0.3, "p50": 0.5, "p90": 0.7, "stddev": 0.1,
    }])
    rel = relative_scores(db, "ep1")
    assert set(rel.keys()) == {"rules"}  # llm_judge has no baseline → skipped
