"""
merger/drift.py

Online drift alerts (EVAL_DEPTH_AND_MEMORY_PLAN §2.6).

A periodic worker job that watches each cluster's recent score against its
persisted baseline (`cluster_baselines`, §1.2) and fires when a cohort has
regressed in production — no version bump needed. A cluster is "drifting" when
its recent-window mean drops more than `k · σ` below the baseline mean (k
configurable; σ is the baseline stddev). Pairs with failure-pattern recurrence
(§1.4): a drifting cluster plus a spiking failure signature is a strong signal.

Detected drifts are written to `drift_alerts` (best-effort; table optional) and
surfaced via the existing `/drift` API. Pure `detect_drift(...)` does the math
so it's unit-testable; `run_drift_alerts(...)` does the DB sweep.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

# How many standard deviations below baseline mean counts as drift.
DRIFT_K = 2.0
# Recent window to measure the live mean over.
RECENT_DAYS = 7
# Need at least this many recent episodes to call drift (avoid noise).
MIN_RECENT = 5


def detect_drift(baseline_mean: float, baseline_std: float, recent_scores: list[float], k: float = DRIFT_K) -> dict | None:
    """Return a drift record if the recent mean is k·σ below baseline, else None.

    A floor of 0.05 on σ avoids hair-trigger alerts on near-constant clusters.
    """
    if len(recent_scores) < MIN_RECENT:
        return None
    recent_mean = sum(recent_scores) / len(recent_scores)
    sigma = max(baseline_std, 0.05)
    threshold = baseline_mean - k * sigma
    if recent_mean < threshold:
        return {
            "baseline_mean": round(baseline_mean, 4),
            "recent_mean": round(recent_mean, 4),
            "drop": round(baseline_mean - recent_mean, 4),
            "sigma": round(sigma, 4),
            "k": k,
            "n_recent": len(recent_scores),
        }
    return None


def run_drift_alerts(client, scorer: str = "custom", k: float = DRIFT_K) -> int:
    """Sweep all clusters with a baseline for the given scorer and record drifts.

    Returns the number of drifting clusters found. Best-effort: a missing table
    anywhere short-circuits to 0 without raising.
    """
    try:
        base_resp = (
            client.table("cluster_baselines")
            .select("cluster_id, scorer, mean, stddev")
            .eq("scorer", scorer)
            .execute()
        )
    except Exception as exc:
        if _MISSING_TABLE in str(exc):
            log.debug("cluster_baselines absent — skipping drift sweep")
            return 0
        raise

    baselines = base_resp.data or []
    if not baselines:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
    found = 0
    for b in baselines:
        cluster_id = b["cluster_id"]
        try:
            recent = _recent_scores(client, cluster_id, scorer, cutoff)
        except Exception as exc:
            log.warning(f"drift recent-score fetch failed for cluster {cluster_id}: {exc}")
            continue

        try:
            mean = float(b["mean"])
            std = float(b.get("stddev") or 0.0)
        except (TypeError, ValueError):
            continue

        drift = detect_drift(mean, std, recent, k=k)
        if drift:
            found += 1
            drift.update({"cluster_id": cluster_id, "scorer": scorer})
            _record_drift(client, drift)
            log.warning(
                f"DRIFT: cluster {cluster_id} scorer={scorer} "
                f"recent={drift['recent_mean']} < baseline={drift['baseline_mean']} "
                f"(drop {drift['drop']})"
            )
    if found:
        log.info(f"drift sweep: {found} drifting cluster(s) for scorer={scorer}")
    return found


def _recent_scores(client, cluster_id: str, scorer: str, cutoff_iso: str) -> list[float]:
    """Scores for the cluster's episodes created since cutoff, for one scorer."""
    eps = (
        client.table("episodes")
        .select("episode_id")
        .eq("cluster_id", cluster_id)
        .gte("created_at", cutoff_iso)
        .execute()
    ).data or []
    ep_ids = [e["episode_id"] for e in eps]
    if not ep_ids:
        return []

    out: list[float] = []
    for i in range(0, len(ep_ids), 100):
        batch = ep_ids[i : i + 100]
        rows = (
            client.table("episode_scores")
            .select("score, scorer")
            .in_("episode_id", batch)
            .eq("scorer", scorer)
            .execute()
        ).data or []
        for r in rows:
            try:
                out.append(float(r["score"]))
            except (TypeError, ValueError, KeyError):
                pass
    return out


def _record_drift(client, drift: dict) -> None:
    """Persist a drift alert (best-effort; table is optional)."""
    try:
        client.table("drift_alerts").insert({
            "cluster_id": drift["cluster_id"],
            "scorer": drift["scorer"],
            "baseline_mean": drift["baseline_mean"],
            "recent_mean": drift["recent_mean"],
            "drop": drift["drop"],
            "n_recent": drift["n_recent"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        if _MISSING_TABLE not in str(exc):
            log.debug(f"drift_alerts insert failed: {exc}")
