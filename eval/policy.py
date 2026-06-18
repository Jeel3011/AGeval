"""
eval/policy.py

Live policies — turn a verdict into enforced behaviour
(LIVE_EVAL_WEDGE_PLAN §2).

A `Verdict` from eval/live.py is *advice*: the engine recommends allow / warn /
escalate, and NEVER blocks on its own. A **policy** is what makes that advice a
product — a per-agent, declarative, versioned rule list that decides what a
verdict actually *does*, including the only path to `block`.

A policy is a list of rules evaluated top-to-bottom; the first matching rule's
`do` wins, else `default` (default: allow). Each rule matches on the verdict's
layers / severity / score::

    {"when": {"layer": "failure", "min_severity": "high"}, "do": "block"}
    {"when": {"layer": "baseline", "min_z": 6},            "do": "escalate"}
    {"when": {"max_score": 0.4},                            "do": "warn"}
    {"default": "allow"}

Safety stance:
  • Absence of a policy → the verdict's own recommended action stands (so a
    high-severity concern still surfaces as `escalate`); AGeval never makes an
    agent *more* broken without a policy.
  • `mode = "log_only"` (the default) → policy decisions are computed and
    recorded for the shadow-vs-enforce diff, but the RETURNED action is capped
    at the advisory level: a `block` decision becomes `escalate` until the user
    flips the policy to `enforce`. Zero-risk adoption.
  • Only `mode = "enforce"` lets a policy return `block`.

Degrades gracefully: a missing `live_policies` table → no policy → advisory
action stands.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

_SEVERITY_RANK = {"info": 0, "warn": 1, "high": 2}
_ACTION_RANK = {"allow": 0, "warn": 1, "escalate": 2, "block": 3}
_VALID_ACTIONS = set(_ACTION_RANK)


def load_active_policy(client, user_id: str, agent_id: str) -> dict | None:
    """Return the agent's highest-version policy row, or None if none/absent."""
    try:
        resp = (
            client.table("live_policies")
            .select("version, mode, rules")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if _MISSING_TABLE not in str(exc):
            log.warning(f"policy: load failed for {agent_id}: {exc}")
        return None
    return (resp.data or [None])[0]


def _rule_matches(when: dict, verdict) -> bool:
    """Does a rule's `when` clause match this verdict?

    All present conditions must hold (AND). Supported keys:
      layer        — at least one reason from this layer
      min_severity — at least one reason at/above this severity
      max_score    — verdict.score <= this
      min_z        — a baseline reason with z >= this
      action       — the verdict's own recommended action equals this
    """
    reasons = [r if isinstance(r, dict) else r.__dict__ for r in (verdict.reasons or [])]

    if "layer" in when:
        if not any(r.get("layer") == when["layer"] for r in reasons):
            return False

    if "min_severity" in when:
        floor = _SEVERITY_RANK.get(when["min_severity"], 0)
        if not any(_SEVERITY_RANK.get(r.get("severity"), 0) >= floor for r in reasons):
            return False

    if "max_score" in when:
        try:
            if verdict.score > float(when["max_score"]):
                return False
        except (TypeError, ValueError):
            return False

    if "min_z" in when:
        try:
            floor = float(when["min_z"])
        except (TypeError, ValueError):
            return False
        zs = [r.get("detail", {}).get("z") for r in reasons if r.get("layer") == "baseline"]
        if not any(z is not None and z >= floor for z in zs):
            return False

    if "action" in when:
        if verdict.action != when["action"]:
            return False

    return True


def apply_policy(client, user_id: str, agent_id: str, verdict):
    """Apply the agent's live policy to a verdict, returning the ENFORCED action.

    Mutates and returns the same verdict. Records what the policy decided on the
    verdict (``policy_decision``, ``policy_mode``, ``policy_enforced``) so the
    dashboard can show "would-have-blocked N runs" before the user flips to
    enforce. Never raises — a policy error leaves the advisory action intact.
    """
    policy = load_active_policy(client, user_id, agent_id)
    if not policy:
        verdict.policy_decision = None
        verdict.policy_mode = None
        return verdict

    rules = policy.get("rules") or []
    decision = None
    for rule in rules:
        if "default" in rule and len(rule) == 1:
            continue  # handle default last
        when = rule.get("when") or {}
        do = rule.get("do")
        if do in _VALID_ACTIONS and _rule_matches(when, verdict):
            decision = do
            break
    if decision is None:
        for rule in rules:
            if rule.get("default") in _VALID_ACTIONS:
                decision = rule["default"]
                break

    mode = policy.get("mode", "log_only")
    verdict.policy_decision = decision
    verdict.policy_mode = mode

    if decision is None:
        return verdict

    # In log_only, a block decision is recorded but NOT enforced — it's capped
    # at escalate so adoption is zero-risk. Only enforce mode can block.
    enforced = decision
    if mode != "enforce" and _ACTION_RANK.get(decision, 0) > _ACTION_RANK["escalate"]:
        enforced = "escalate"

    # The policy can only ever make the action *stricter* than the advisory one,
    # never looser — a policy must not silently downgrade a high-severity concern.
    if _ACTION_RANK.get(enforced, 0) >= _ACTION_RANK.get(verdict.action, 0):
        verdict.action = enforced

    verdict.policy_enforced = (verdict.action == decision and mode == "enforce")
    return verdict
