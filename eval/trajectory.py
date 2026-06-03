"""
eval/trajectory.py

Trajectory adherence (EVAL_DEPTH_AND_MEMORY_PLAN §1.3 / §2.1).

Scores how closely a run's tool sequence follows the *golden trajectory* mined
for its task cluster (merger/procedural.py). The score is 1 minus the
normalised Levenshtein (edit) distance between the run's meaningful tool
sequence and the golden sequence — so an identical path scores 1.0 and a
completely different path scores ~0.0. This catches "wrong path, right answer":
a run can produce a fine final output while taking a degenerate or unexpected
route, and adherence surfaces that.

Persisted as the `trajectory` scorer in `episode_scores` (its own row, like
`rules` / `custom` / `llm_judge`). Returns ``None`` — and writes nothing — when
the episode has no cluster or its cluster has no golden path yet (cold start),
so callers simply have no trajectory score rather than a misleading 0.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from merger.fingerprint import tool_sequence

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"


def levenshtein(a: list[str], b: list[str]) -> int:
    """Classic edit distance between two token sequences (insert/delete/sub)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost, # substitution
            ))
        prev = cur
    return prev[-1]


def adherence(run_seq: list[str], golden_seq: list[str]) -> float:
    """Normalised similarity in [0, 1]: 1 - edit_distance / max(len)."""
    if not run_seq and not golden_seq:
        return 1.0
    dist = levenshtein(run_seq, golden_seq)
    denom = max(len(run_seq), len(golden_seq)) or 1
    return round(max(0.0, 1.0 - dist / denom), 4)


def score_trajectory_adherence(client, episode_id: str) -> dict | None:
    """Compute and persist the trajectory-adherence score for an episode.

    Returns the result dict ({episode_id, scorer, score, breakdown}) on success,
    or ``None`` when there is no golden path to compare against (unclustered, or
    cluster not yet mined). Best-effort on a missing table.
    """
    ep_resp = (
        client.table("episodes")
        .select("cluster_id")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep_resp.data:
        return None
    cluster_id = ep_resp.data[0].get("cluster_id")
    if not cluster_id:
        return None

    try:
        pm_resp = (
            client.table("procedural_memory")
            .select("golden_sequence, expected_steps, n")
            .eq("cluster_id", cluster_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if _MISSING_TABLE in str(exc):
            return None
        raise
    if not pm_resp.data:
        return None

    golden = pm_resp.data[0].get("golden_sequence") or []
    if isinstance(golden, str):
        import json
        try:
            golden = json.loads(golden)
        except ValueError:
            return None

    steps_resp = (
        client.table("episode_steps")
        .select("step_index, tool_name, success")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    )
    run_seq = tool_sequence(steps_resp.data or [])

    score = adherence(run_seq, golden)
    breakdown = {
        "trajectory_adherence": score,
        "run_length": len(run_seq),
        "golden_length": len(golden),
        "edit_distance": levenshtein(run_seq, golden),
    }
    result = {
        "episode_id": episode_id,
        "scorer": "trajectory",
        "score": score,
        "breakdown": breakdown,
    }

    try:
        client.table("episode_scores").upsert({
            "episode_id": episode_id,
            "scorer": "trajectory",
            "score": score,
            "breakdown": breakdown,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="episode_id,scorer").execute()
    except Exception as exc:
        log.warning(f"Failed to write trajectory score for {episode_id}: {exc}")

    return result
