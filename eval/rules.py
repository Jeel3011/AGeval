"""
eval/rules.py

Deterministic rule-based scorer. No LLM involved.
Reads episode_steps, produces a score between 0.0 and 1.0,
writes the result to episode_scores.

Metrics (equal weight, each 0–1):
  1. success_rate        — steps that succeeded / total steps
  2. recovery_rate       — env_errors that were followed by a success / total env_errors
  3. reasoning_coverage  — steps that have non-null reasoning / total steps
  4. efficiency_score    — penalises redundant tool calls (same tool called 2+ times in a row)

Final score = mean of all four metrics.

Usage:
    from eval.rules import score_episode
    result = score_episode(client, episode_id)
    print(result)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def score_episode(client, episode_id: str) -> dict:
    """
    Score one episode using rule-based metrics.
    Writes result to episode_scores and returns the full breakdown dict.

    Returns dict with keys: episode_id, score, breakdown, scorer
    Raises if episode_steps is empty — can't score what doesn't exist.
    """
    steps = fetch_steps(client, episode_id)

    if not steps:
        raise ValueError(f"No steps found for episode_id={episode_id}. Cannot score.")

    breakdown = {
        "success_rate"      : calc_success_rate(steps),
        "recovery_rate"     : calc_recovery_rate(steps),
        "reasoning_coverage": calc_reasoning_coverage(steps),
        "efficiency_score"  : calc_efficiency_score(steps),
    }

    # Final score: simple mean of all metrics
    score = round(sum(breakdown.values()) / len(breakdown), 4)

    result = {
        "episode_id": episode_id,
        "scorer"    : "rules",
        "score"     : score,
        "breakdown" : breakdown,
    }

    write_score(client, result)
    

    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def calc_success_rate(steps: list[dict]) -> float:
    """
    Fraction of steps that succeeded.
    0 steps → 0.0 (handled before this is called).
    All succeed → 1.0. All fail → 0.0.
    """
    return round(sum(1 for s in steps if s.get("success")) / len(steps), 4)


def calc_recovery_rate(steps: list[dict]) -> float:
    """
    Of all env_errors, how many were followed by a successful step?
    Measures whether the agent actually recovered from transient failures.

    If no env_errors exist → 1.0 (full marks, nothing to recover from).
    If env_errors exist but none recovered → 0.0.

    Only counts env_error, not agent_error — retrying an agent_error
    is not recovery, it's repeated failure.
    """
    env_error_indices = [
        s["step_index"] for s in steps
        if s.get("error_category") == "env_error"
    ]

    if not env_error_indices:
        return 1.0

    # build a lookup: step_index → success
    success_by_index = {s["step_index"]: s.get("success", False) for s in steps}
    max_index = max(s["step_index"] for s in steps)

    recovered = 0
    for idx in env_error_indices:
        # check if any subsequent step succeeded
        for next_idx in range(idx + 1, max_index + 1):
            if success_by_index.get(next_idx):
                recovered += 1
                break

    return round(recovered / len(env_error_indices), 4)


def calc_reasoning_coverage(steps: list[dict]) -> float:
    """
    Fraction of steps where the agent provided reasoning before the tool call.
    Null or empty reasoning → not covered.

    This measures observability quality — how often can you explain
    WHY the agent made a particular tool call.
    """
    covered = sum(
        1 for s in steps
        if s.get("reasoning") and str(s["reasoning"]).strip()
    )
    return round(covered / len(steps), 4)


def calc_efficiency_score(steps: list[dict]) -> float:
    """
    Penalises consecutive duplicate tool calls — same tool name back to back.
    These usually indicate the agent got stuck repeating itself.

    No duplicates → 1.0
    All consecutive duplicates → 0.0
    Partial → proportional penalty.

    Formula: 1 - (consecutive_duplicates / (total_steps - 1))
    Edge case: 1 step → 1.0 (no consecutive pairs to evaluate).
    """
    if len(steps) <= 1:
        return 1.0

    sorted_steps = sorted(steps, key=lambda s: s["step_index"])
    duplicates = sum(
        1 for i in range(1, len(sorted_steps))
        if sorted_steps[i]["tool_name"] == sorted_steps[i - 1]["tool_name"]
    )

    return round(1 - (duplicates / (len(steps) - 1)), 4)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------
def fetch_steps(client, episode_id: str) -> list[dict]:
    resp = client.table("episode_steps") \
        .select("step_index, tool_name, success, error_category, is_recoverable, reasoning, latency_ms") \
        .eq("episode_id", episode_id) \
        .order("step_index") \
        .execute()
    return resp.data or []


def write_score(client, result: dict) -> None:
    """
    Upsert score row. If the episode was already scored by 'rules',
    overwrite it — re-running the scorer should update, not duplicate.
    """
    client.table("episode_scores").upsert({
        "episode_id": result["episode_id"],
        "scorer"    : result["scorer"],
        "score"     : str(result["score"]),  # numeric type needs string for supabase-py
        "breakdown" : result["breakdown"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="episode_id,scorer").execute()