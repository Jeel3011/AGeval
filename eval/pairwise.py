"""
eval/pairwise.py

Pairwise / A-B trajectory comparison (EVAL_DEPTH_AND_MEMORY_PLAN §2.4).

Given two episodes (e.g. two agent versions on the same task), produce:

  • a deterministic trajectory diff — tool-sequence alignment, step-count and
    outcome deltas, per-scorer score deltas (no LLM, always available);
  • an optional LLM-judge pairwise verdict — which run is better and why
    (opt-in, bounded spend; skipped when OPENAI_API_KEY is absent).

The deterministic half is pure (`compare_trajectories`) so it's testable against
the in-memory fake; `compare_episodes` does the DB fetch + optional LLM call.
"""

from __future__ import annotations

import json
import logging
import os

from eval.trajectory import levenshtein
from merger.fingerprint import tool_sequence

log = logging.getLogger(__name__)


def _seq_diff(a: list[str], b: list[str]) -> list[dict]:
    """A compact LCS-based alignment of two tool sequences.

    Returns ops: {"op": "same"|"a_only"|"b_only", "tool": name}. Useful for the
    UI to render a side-by-side path diff.
    """
    n, m = len(a), len(b)
    # LCS table.
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

    ops: list[dict] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            ops.append({"op": "same", "tool": a[i]})
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append({"op": "a_only", "tool": a[i]})
            i += 1
        else:
            ops.append({"op": "b_only", "tool": b[j]})
            j += 1
    while i < n:
        ops.append({"op": "a_only", "tool": a[i]})
        i += 1
    while j < m:
        ops.append({"op": "b_only", "tool": b[j]})
        j += 1
    return ops


def compare_trajectories(ep_a: dict, ep_b: dict) -> dict:
    """Deterministic diff between two episode dicts.

    Each episode dict carries: episode_id, outcome, steps (list), scores
    ({scorer: score}).
    """
    seq_a = tool_sequence(ep_a.get("steps", []))
    seq_b = tool_sequence(ep_b.get("steps", []))

    scores_a = ep_a.get("scores", {})
    scores_b = ep_b.get("scores", {})
    score_deltas = {}
    for scorer in sorted(set(scores_a) | set(scores_b)):
        a, b = scores_a.get(scorer), scores_b.get(scorer)
        delta = round(b - a, 4) if (a is not None and b is not None) else None
        score_deltas[scorer] = {"a": a, "b": b, "delta": delta}

    return {
        "a": {"episode_id": ep_a.get("episode_id"), "outcome": ep_a.get("outcome"),
              "steps": len(seq_a), "sequence": seq_a},
        "b": {"episode_id": ep_b.get("episode_id"), "outcome": ep_b.get("outcome"),
              "steps": len(seq_b), "sequence": seq_b},
        "sequence_diff": _seq_diff(seq_a, seq_b),
        "edit_distance": levenshtein(seq_a, seq_b),
        "step_delta": len(seq_b) - len(seq_a),
        "score_deltas": score_deltas,
    }


def _llm_pairwise(ep_a: dict, ep_b: dict) -> dict | None:
    """Optional LLM verdict on which run is better. None if no API key."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None

    def summarise(ep):
        seq = " → ".join(tool_sequence(ep.get("steps", []))) or "(no tools)"
        return (
            f"outcome={ep.get('outcome')}; tools: {seq}; "
            f"final_output={json.dumps(ep.get('final_output'))[:500]}"
        )

    prompt = (
        "You are comparing two agent runs on the same task. Decide which run is "
        "better overall (trajectory quality + outcome), or if they tie.\n\n"
        f"Task: {ep_a.get('task') or ep_b.get('task') or 'unknown'}\n\n"
        f"Run A: {summarise(ep_a)}\n"
        f"Run B: {summarise(ep_b)}\n\n"
        'Return JSON exactly: {"winner": "a"|"b"|"tie", "reasoning": "string"}'
    )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        raw = (resp.choices[0].message.content or "").strip().strip("```json").strip("```")
        data = json.loads(raw)
        winner = data.get("winner")
        if winner not in ("a", "b", "tie"):
            winner = "tie"
        return {"winner": winner, "reasoning": data.get("reasoning", "")}
    except Exception as exc:
        log.warning(f"pairwise LLM judge failed: {exc}")
        return None


def _load_episode(db, episode_id: str, user_id: str) -> dict | None:
    ep = (
        db.table("episodes")
        .select("episode_id, task, outcome, final_output, user_id")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep.data or ep.data[0].get("user_id") != user_id:
        return None
    row = ep.data[0]
    steps = (
        db.table("episode_steps")
        .select("step_index, tool_name, success")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    ).data or []
    score_rows = (
        db.table("episode_scores")
        .select("scorer, score")
        .eq("episode_id", episode_id)
        .execute()
    ).data or []
    scores = {}
    for s in score_rows:
        try:
            scores[s["scorer"]] = float(s["score"])
        except (TypeError, ValueError, KeyError):
            pass
    row["steps"] = steps
    row["scores"] = scores
    return row


def compare_episodes(db, user_id: str, episode_a: str, episode_b: str, use_llm: bool = True) -> dict:
    """DB-backed pairwise comparison used by the endpoint. Scopes to the user."""
    ep_a = _load_episode(db, episode_a, user_id)
    ep_b = _load_episode(db, episode_b, user_id)
    if ep_a is None or ep_b is None:
        raise ValueError("One or both episodes not found for this user")

    result = compare_trajectories(ep_a, ep_b)
    if use_llm:
        verdict = _llm_pairwise(ep_a, ep_b)
        if verdict:
            result["llm_verdict"] = verdict
    return result
