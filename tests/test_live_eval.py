"""
tests/test_live_eval.py

Tests for the Live Verdict engine (LIVE_EVAL_WEDGE_PLAN §1) — the wedge.

Covers the three deterministic / vector layers of eval/live.py:
  • failure-signature match   (cosine vs failure_memory centroids)
  • baseline outlier check     (z-score vs numeric input baselines)
  • procedural deviation       (golden-path prefix adherence)

…plus the cold-start fail-open contract, the worst-action combination rule,
and load_snapshot's graceful degradation on an empty/un-migrated DB.

All pure CPU — no network, no LLM. The failure-match layer is fed precomputed
embeddings (the API embeds the step intent before calling evaluate_step).
"""

from __future__ import annotations

from eval.live import (
    FAILURE_MATCH_THRESHOLD,
    MIN_SIGNATURE_OCCURRENCES,
    MemorySnapshot,
    Verdict,
    _cosine,
    evaluate_step,
    load_snapshot,
)
from tests.fakes import FakeSupabase


# ---------------------------------------------------------------------------
# cosine helper
# ---------------------------------------------------------------------------
def test_cosine_basics():
    assert _cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert _cosine([1, 0], [0, 1]) == 0.0
    assert _cosine([], [1]) == 0.0          # mismatched / empty → 0, never raises
    assert round(_cosine([1, 1], [1, 0]), 4) == 0.7071


# ---------------------------------------------------------------------------
# cold start → fail open
# ---------------------------------------------------------------------------
def test_empty_snapshot_allows():
    v = evaluate_step(MemorySnapshot(), tool_name="charge", tool_input={"amount": 5})
    assert v.action == "allow"
    assert v.confidence == 0.0
    assert v.reasons == []
    assert v.blocked is False


# ---------------------------------------------------------------------------
# layer 1 — failure signature match
# ---------------------------------------------------------------------------
def _sig(occ, centroid, sig_id="sig1"):
    return {
        "id": sig_id, "signature": "env|charge|late", "label": "charge timeout",
        "occurrences": occ, "_centroid": centroid,
    }


def test_failure_match_recurrent_escalates():
    snap = MemorySnapshot(signatures=[_sig(MIN_SIGNATURE_OCCURRENCES + 5, [1.0, 0.0, 0.0])])
    v = evaluate_step(snap, tool_name="charge", tool_input={}, step_embedding=[1.0, 0.0, 0.0])
    assert v.action == "escalate"
    assert v.matched_signature_id == "sig1"
    assert v.reasons[0].layer == "failure"
    assert v.confidence > 0.0


def test_failure_match_rare_only_warns():
    # A signature seen fewer than MIN_SIGNATURE_OCCURRENCES times is not a
    # pattern yet → at most a warning, never an escalation.
    snap = MemorySnapshot(signatures=[_sig(1, [1.0, 0.0, 0.0])])
    v = evaluate_step(snap, tool_name="charge", tool_input={}, step_embedding=[1.0, 0.0, 0.0])
    assert v.action == "warn"


def test_failure_no_match_below_threshold_allows():
    snap = MemorySnapshot(signatures=[_sig(9, [1.0, 0.0, 0.0])])
    # Orthogonal embedding → cosine 0 < threshold → no match.
    v = evaluate_step(snap, tool_name="charge", tool_input={}, step_embedding=[0.0, 1.0, 0.0])
    assert v.action == "allow"
    assert v.matched_signature_id is None


# ---------------------------------------------------------------------------
# layer 2 — baseline outlier
# ---------------------------------------------------------------------------
def test_baseline_outlier_escalates_with_suggestion():
    snap = MemorySnapshot(numeric_baselines={
        "charge.amount": {"mean": 42.0, "std": 5.0, "p10": 35, "p90": 50, "n": 60},
    })
    v = evaluate_step(snap, tool_name="charge", tool_input={"amount": 4200})
    assert v.action == "escalate"
    assert v.suggest == {"amount": 42.0}     # repair hint = the typical value
    assert v.reasons[0].layer == "baseline"


def test_baseline_within_band_allows():
    snap = MemorySnapshot(numeric_baselines={
        "charge.amount": {"mean": 42.0, "std": 5.0, "p10": 35, "p90": 50, "n": 60},
    })
    v = evaluate_step(snap, tool_name="charge", tool_input={"amount": 44})
    assert v.action == "allow"


def test_baseline_ignored_below_volume_gate():
    # n below MIN_BASELINE_N → not trustworthy → layer doesn't fire.
    snap = MemorySnapshot(numeric_baselines={
        "charge.amount": {"mean": 42.0, "std": 5.0, "p10": 35, "p90": 50, "n": 3},
    })
    v = evaluate_step(snap, tool_name="charge", tool_input={"amount": 4200})
    assert v.action == "allow"


def test_baseline_skips_non_numeric_and_bool():
    snap = MemorySnapshot(numeric_baselines={
        "charge.amount": {"mean": 42.0, "std": 5.0, "p10": 35, "p90": 50, "n": 60},
    })
    # bool is a subclass of int but must NOT be treated as a numeric outlier.
    v = evaluate_step(snap, tool_name="charge", tool_input={"amount": True, "note": "x"})
    assert v.action == "allow"


# ---------------------------------------------------------------------------
# layer 3 — procedural deviation
# ---------------------------------------------------------------------------
def test_procedural_deviation_warns():
    snap = MemorySnapshot(golden={"golden_sequence": ["search", "select", "book", "pay"], "n": 30})
    v = evaluate_step(snap, tool_name="nuke", tools_so_far=["nuke", "wipe", "delete"])
    assert v.action == "warn"
    assert v.reasons[0].layer == "procedural"


def test_procedural_on_path_allows():
    snap = MemorySnapshot(golden={"golden_sequence": ["search", "select", "book", "pay"], "n": 30})
    v = evaluate_step(snap, tool_name="book", tools_so_far=["search", "select", "book"])
    assert v.action == "allow"


# ---------------------------------------------------------------------------
# combination — worst action wins, penalties stack
# ---------------------------------------------------------------------------
def test_high_severity_beats_warn():
    snap = MemorySnapshot(
        signatures=[_sig(9, [1.0, 0.0, 0.0])],
        golden={"golden_sequence": ["a", "b", "c"], "n": 30},
    )
    # failure match (high → escalate) + procedural deviation (warn) → escalate.
    v = evaluate_step(
        snap, tool_name="charge", tool_input={}, step_embedding=[1.0, 0.0, 0.0],
        tools_so_far=["x", "y", "z"],
    )
    assert v.action == "escalate"
    assert len(v.reasons) == 2
    assert v.score < 0.5      # two concerns, one high → meaningfully docked


# ---------------------------------------------------------------------------
# Verdict serialization round-trip
# ---------------------------------------------------------------------------
def test_verdict_to_dict_roundtrip():
    snap = MemorySnapshot(numeric_baselines={
        "charge.amount": {"mean": 42.0, "std": 5.0, "p10": 35, "p90": 50, "n": 60},
    })
    v = evaluate_step(snap, tool_name="charge", tool_input={"amount": 4200})
    d = v.to_dict()
    assert d["action"] == "escalate"
    assert isinstance(d["reasons"], list)
    assert d["reasons"][0]["layer"] == "baseline"   # Reason flattened to dict


# ---------------------------------------------------------------------------
# load_snapshot degrades gracefully
# ---------------------------------------------------------------------------
def test_load_snapshot_empty_db_is_empty_not_error():
    db = FakeSupabase()
    snap = load_snapshot(db, user_id="u1", agent_id="a1")
    assert isinstance(snap, MemorySnapshot)
    assert snap.empty


def test_load_snapshot_pulls_signatures_and_golden():
    db = FakeSupabase()
    db.table("failure_memory").insert({
        "id": "s1", "user_id": "u1", "agent_id": "a1",
        "signature": "env|charge|late", "label": "timeout",
        "centroid": [0.1, 0.2, 0.3], "occurrences": 7,
    }).execute()
    db.table("procedural_memory").insert({
        "user_id": "u1", "agent_id": "a1",
        "golden_sequence": ["search", "book"], "n": 25,
    }).execute()
    snap = load_snapshot(db, user_id="u1", agent_id="a1")
    assert len(snap.signatures) == 1
    assert snap.signatures[0]["_centroid"] == [0.1, 0.2, 0.3]   # centroid parsed
    assert snap.golden["golden_sequence"] == ["search", "book"]
    assert not snap.empty
