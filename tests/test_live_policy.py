"""
tests/test_live_policy.py

Tests for Phase-B of the live-eval wedge (LIVE_EVAL_WEDGE_PLAN §2 + §1 outlier):
  • eval/policy.py            — verdict → enforced action (the only path to block)
  • merger/input_baselines.py — mining numeric tool-input distributions

Pure CPU against the in-memory FakeSupabase — no network, no LLM.
"""

from __future__ import annotations

from eval.live import Reason, Verdict
from eval.policy import _rule_matches, apply_policy, load_active_policy
from merger.input_baselines import MIN_INPUT_N, _numeric_fields, mine_input_baselines
from tests.fakes import FakeSupabase


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _verdict(action="escalate", score=0.5, reasons=None):
    return Verdict(action=action, score=score, reasons=reasons or [])


def _high_failure():
    return Reason(layer="failure", message="known failure", severity="high",
                  detail={"occurrences": 9})


def _baseline(z=8.0):
    return Reason(layer="baseline", message="outlier", severity="high",
                  detail={"z": z, "field": "charge.amount"})


# ---------------------------------------------------------------------------
# rule matching
# ---------------------------------------------------------------------------
def test_rule_matches_layer_and_severity():
    v = _verdict(reasons=[_high_failure()])
    assert _rule_matches({"layer": "failure"}, v)
    assert _rule_matches({"min_severity": "high"}, v)
    assert not _rule_matches({"layer": "procedural"}, v)


def test_rule_matches_min_z():
    v = _verdict(reasons=[_baseline(z=8.0)])
    assert _rule_matches({"min_z": 6}, v)
    assert not _rule_matches({"min_z": 10}, v)


def test_rule_matches_max_score():
    v = _verdict(score=0.3)
    assert _rule_matches({"max_score": 0.4}, v)
    assert not _rule_matches({"max_score": 0.2}, v)


# ---------------------------------------------------------------------------
# apply_policy — the safety contract
# ---------------------------------------------------------------------------
def _db_with_policy(mode, rules, user="u1", agent="a1"):
    db = FakeSupabase()
    db.table("live_policies").insert({
        "user_id": user, "agent_id": agent, "version": 1,
        "mode": mode, "rules": rules,
    }).execute()
    return db


def test_no_policy_leaves_advisory_action():
    db = FakeSupabase()
    v = apply_policy(db, "u1", "a1", _verdict(action="escalate"))
    assert v.action == "escalate"
    assert v.policy_decision is None


def test_log_only_caps_block_at_escalate():
    # A block rule in log_only mode must NOT actually block — capped at escalate.
    db = _db_with_policy("log_only", [
        {"when": {"layer": "failure", "min_severity": "high"}, "do": "block"},
        {"default": "allow"},
    ])
    v = apply_policy(db, "u1", "a1", _verdict(action="escalate", reasons=[_high_failure()]))
    assert v.policy_decision == "block"      # decision recorded for the shadow diff
    assert v.action == "escalate"            # …but NOT enforced
    assert v.policy_enforced is False


def test_enforce_mode_blocks():
    db = _db_with_policy("enforce", [
        {"when": {"layer": "failure", "min_severity": "high"}, "do": "block"},
        {"default": "allow"},
    ])
    v = apply_policy(db, "u1", "a1", _verdict(action="escalate", reasons=[_high_failure()]))
    assert v.policy_decision == "block"
    assert v.action == "block"
    assert v.policy_enforced is True
    assert v.blocked is True


def test_policy_never_loosens_action():
    # Advisory escalate + a policy that says 'warn' → must stay escalate (a policy
    # can only make things stricter, never silently downgrade a real concern).
    db = _db_with_policy("enforce", [
        {"when": {"layer": "failure"}, "do": "warn"},
        {"default": "allow"},
    ])
    v = apply_policy(db, "u1", "a1", _verdict(action="escalate", reasons=[_high_failure()]))
    assert v.action == "escalate"


def test_first_matching_rule_wins():
    db = _db_with_policy("enforce", [
        {"when": {"min_z": 6}, "do": "block"},
        {"when": {"layer": "baseline"}, "do": "warn"},
        {"default": "allow"},
    ])
    v = apply_policy(db, "u1", "a1", _verdict(action="escalate", reasons=[_baseline(z=8)]))
    assert v.policy_decision == "block"


def test_default_applies_when_no_rule_matches():
    db = _db_with_policy("enforce", [
        {"when": {"layer": "procedural"}, "do": "block"},
        {"default": "allow"},
    ])
    v = apply_policy(db, "u1", "a1", _verdict(action="warn", reasons=[_baseline()]))
    assert v.policy_decision == "allow"


def test_no_rows_degrades_to_no_policy():
    # No policy rows (or an un-migrated table that returns nothing) → None, so
    # the verdict's advisory action stands.
    db = FakeSupabase()
    assert load_active_policy(db, "u1", "a1") is None


# ---------------------------------------------------------------------------
# input baselines mining
# ---------------------------------------------------------------------------
def test_numeric_fields_excludes_bool_and_nested():
    assert _numeric_fields({"amount": 42, "ok": True, "meta": {"x": 1}, "name": "a"}) == {"amount": 42.0}


def test_mine_input_baselines_writes_for_sufficient_samples():
    db = FakeSupabase()
    # One episode owned by the agent…
    db.table("episodes").insert({
        "episode_id": "ep1", "user_id": "u1", "agent_id": "a1",
    }).execute()
    # …with >= MIN_INPUT_N successful charge steps around amount≈42.
    for i in range(MIN_INPUT_N + 5):
        db.table("episode_steps").insert({
            "episode_id": "ep1", "step_index": i, "tool_name": "charge",
            "tool_input": {"amount": 40 + (i % 5)}, "success": True,
        }).execute()

    written = mine_input_baselines(db, "u1", "a1")
    assert written == 1
    rows = db.table("tool_input_baselines").select("*").execute().data
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_name"] == "charge" and r["field"] == "amount"
    assert r["n"] >= MIN_INPUT_N
    assert 40 <= r["mean"] <= 45
    assert r["std"] is not None      # mapped from _distribution's 'stddev'


def test_mine_input_baselines_skips_below_gate():
    db = FakeSupabase()
    db.table("episodes").insert({"episode_id": "ep1", "user_id": "u1", "agent_id": "a1"}).execute()
    for i in range(3):  # below MIN_INPUT_N
        db.table("episode_steps").insert({
            "episode_id": "ep1", "step_index": i, "tool_name": "charge",
            "tool_input": {"amount": 42}, "success": True,
        }).execute()
    assert mine_input_baselines(db, "u1", "a1") == 0
