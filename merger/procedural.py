"""
merger/procedural.py

Procedural memory — the "golden trajectory" (EVAL_DEPTH_AND_MEMORY_PLAN §1.3).

For each task cluster we mine *how the task should be done*: the modal
successful tool sequence, the expected step count, and the expected tool set —
distilled from the cluster's highest-scoring successful episodes. A new run is
then scored by how closely its tool sequence follows this golden path
(`eval/trajectory.py`), which catches "wrong path, right answer".

Runs inside the clustering job (per cluster, service_role), right after the
baselines are computed. Degrades gracefully: a missing `procedural_memory`
table or too-few exemplars → log + skip, clustering still completes.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from merger.fingerprint import tool_sequence

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

# Need at least this many good exemplars before a golden path is meaningful.
MIN_EXEMPLARS = 3
# Mine the golden path from the top fraction of successful runs by score.
TOP_FRACTION = 0.5


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _select_exemplars(scored: list[dict]) -> list[dict]:
    """Pick the top-scoring successful episodes to mine the golden path from.

    `scored` items are {episode_id, score, outcome}. Prefers successful runs;
    takes the top TOP_FRACTION by score (at least MIN_EXEMPLARS if available).
    """
    successful = [e for e in scored if e.get("outcome") == "success" and e.get("score") is not None]
    pool = successful or [e for e in scored if e.get("score") is not None]
    if len(pool) < MIN_EXEMPLARS:
        return []
    pool.sort(key=lambda e: e["score"], reverse=True)
    cutoff = max(MIN_EXEMPLARS, int(round(len(pool) * TOP_FRACTION)))
    return pool[:cutoff]


def mine_golden_trajectory(
    client,
    cluster_id: str,
    user_id: str,
    agent_id: str,
    episode_ids: list[str],
) -> bool:
    """Mine and persist the golden trajectory for one cluster.

    Returns True if a row was written, False if skipped (too few exemplars,
    missing table, etc.). Never raises on a missing table.
    """
    if not episode_ids:
        return False

    # Pull each episode's best available score + outcome.
    scored = _episode_scores(client, episode_ids)
    exemplars = _select_exemplars(scored)
    if not exemplars:
        log.info(f"procedural_memory: not enough exemplars for cluster {cluster_id}")
        return False

    ex_ids = [e["episode_id"] for e in exemplars]
    sequences = _tool_sequences(client, ex_ids)
    sequences = [seq for seq in sequences.values() if seq]
    if len(sequences) < MIN_EXEMPLARS:
        return False

    # Golden path = the most common exact tool sequence among exemplars.
    seq_counts = Counter(tuple(seq) for seq in sequences)
    golden_seq = list(seq_counts.most_common(1)[0][0])

    expected_steps = _median([float(len(seq)) for seq in sequences])
    # Tools that appear in a majority of exemplar runs = the expected tool set.
    tool_freq: Counter = Counter()
    for seq in sequences:
        tool_freq.update(set(seq))
    threshold = len(sequences) / 2.0
    expected_tools = sorted(t for t, c in tool_freq.items() if c >= threshold)

    row = {
        "cluster_id": cluster_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "golden_sequence": golden_seq,
        "expected_steps": round(expected_steps, 2),
        "expected_tools": expected_tools,
        "n": len(sequences),
        "sample_episode_id": ex_ids[0],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        client.table("procedural_memory").upsert(row, on_conflict="cluster_id").execute()
    except Exception as exc:
        if _MISSING_TABLE in str(exc):
            log.warning("procedural_memory table missing — run sdk/schema.sql; skipping")
            return False
        log.warning(f"procedural_memory upsert failed for cluster {cluster_id}: {exc}")
        return False

    log.info(
        f"procedural_memory: cluster {cluster_id} golden path = {golden_seq} "
        f"(from {len(sequences)} exemplars)"
    )
    return True


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------
def _episode_scores(client, episode_ids: list[str]) -> list[dict]:
    """Return [{episode_id, score, outcome}] using the rules/custom composite.

    Uses whichever deterministic composite is present (prefers 'custom', then
    'rules'); the LLM judge is intentionally ignored so golden-path selection
    stays deterministic and free.
    """
    outcomes: dict[str, str | None] = {}
    for i in range(0, len(episode_ids), 100):
        batch = episode_ids[i : i + 100]
        resp = client.table("episodes").select("episode_id, outcome").in_("episode_id", batch).execute()
        for r in resp.data or []:
            outcomes[r["episode_id"]] = r.get("outcome")

    best: dict[str, float] = {}
    for i in range(0, len(episode_ids), 100):
        batch = episode_ids[i : i + 100]
        resp = (
            client.table("episode_scores")
            .select("episode_id, scorer, score")
            .in_("episode_id", batch)
            .execute()
        )
        for r in resp.data or []:
            if r.get("scorer") == "llm_judge":
                continue
            try:
                score = float(r["score"])
            except (TypeError, ValueError, KeyError):
                continue
            # Keep the highest deterministic score seen per episode.
            if r["episode_id"] not in best or score > best[r["episode_id"]]:
                best[r["episode_id"]] = score

    return [
        {"episode_id": eid, "score": best.get(eid), "outcome": outcomes.get(eid)}
        for eid in episode_ids
    ]


def _tool_sequences(client, episode_ids: list[str]) -> dict[str, list[str]]:
    """Map each episode_id → its meaningful tool sequence."""
    result: dict[str, list[str]] = {}
    for i in range(0, len(episode_ids), 100):
        batch = episode_ids[i : i + 100]
        resp = (
            client.table("episode_steps")
            .select("episode_id, step_index, tool_name, success")
            .in_("episode_id", batch)
            .execute()
        )
        by_ep: dict[str, list[dict]] = {}
        for r in resp.data or []:
            by_ep.setdefault(r["episode_id"], []).append(r)
        for eid, steps in by_ep.items():
            result[eid] = tool_sequence(steps)
    return result
