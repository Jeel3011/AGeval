"""
merger/baselines.py

Cluster baselines — semantic memory made evaluative
(EVAL_DEPTH_AND_MEMORY_PLAN §1.2 + §2.3).

Today the clustering job knows which episodes belong to which task cluster.
This module turns that grouping into *calibrated expectations*: for each
(cluster, scorer) it persists the score distribution (n, mean, p10/p50/p90,
stddev) into `cluster_baselines`. A new episode can then be scored RELATIVE to
its peers ("this run's score is in the bottom 10% of runs like it"), and the
dashboard can show confidence intervals instead of bare point estimates.

Cold-start guard: a baseline is only persisted when n ≥ MIN_BASELINE_N, so we
never present peer-relative signal computed from a handful of runs.

Degrades gracefully: if `cluster_baselines` is absent (schema not migrated) we
log once and skip — the clustering job still completes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

# Minimum sample size before a cluster baseline is trustworthy. Mirrors the
# plan's "gate relative scoring behind n ≥ 20" guidance.
MIN_BASELINE_N = 20


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in [0, 100]). Assumes sorted input."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _distribution(values: list[float]) -> dict:
    """Compute mean/p10/p50/p90/stddev for a list of scores."""
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    sorted_vals = sorted(values)
    return {
        "n": n,
        "mean": round(mean, 4),
        "p10": round(_percentile(sorted_vals, 10), 4),
        "p50": round(_percentile(sorted_vals, 50), 4),
        "p90": round(_percentile(sorted_vals, 90), 4),
        "stddev": round(var ** 0.5, 4),
    }


def compute_baselines(client, cluster_id: str, episode_ids: list[str]) -> int:
    """Recompute and persist score baselines for one cluster.

    Pulls every episode_scores row for the cluster's episodes, groups by scorer
    (rules / llm_judge / custom), and upserts a distribution row per scorer once
    it clears MIN_BASELINE_N. Returns the number of baseline rows written.
    """
    if not episode_ids:
        return 0

    by_scorer: dict[str, list[float]] = {}
    # Batch the IN() lookup to stay under PostgREST URL limits.
    for i in range(0, len(episode_ids), 100):
        batch = episode_ids[i : i + 100]
        resp = (
            client.table("episode_scores")
            .select("scorer, score")
            .in_("episode_id", batch)
            .execute()
        )
        for row in resp.data or []:
            scorer = row.get("scorer")
            try:
                by_scorer.setdefault(scorer, []).append(float(row["score"]))
            except (TypeError, ValueError, KeyError):
                continue

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for scorer, values in by_scorer.items():
        if len(values) < MIN_BASELINE_N:
            continue
        dist = _distribution(values)
        row = {"cluster_id": cluster_id, "scorer": scorer, "updated_at": now, **dist}
        try:
            client.table("cluster_baselines").upsert(
                row, on_conflict="cluster_id,scorer"
            ).execute()
            written += 1
        except Exception as exc:
            if _MISSING_TABLE in str(exc):
                log.warning("cluster_baselines table missing — run sdk/schema.sql; skipping")
                return written
            log.warning(f"cluster_baselines upsert failed (cluster={cluster_id}, scorer={scorer}): {exc}")

    if written:
        log.info(f"cluster_baselines: wrote {written} baseline(s) for cluster {cluster_id}")
    return written
