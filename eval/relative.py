"""
eval/relative.py

Peer-relative & statistical scoring (EVAL_DEPTH_AND_MEMORY_PLAN §1.2 + §2.3).

Turns a bare score (`0.79`) into peer-relative signal by comparing it against
its task cluster's baseline distribution (`cluster_baselines`, written by the
clustering job). For each scorer we report:

  • percentile  — where this run sits within runs like it (0–100)
  • band        — a human label ("bottom 10% of runs like it", "typical", …)
  • confidence  — how trustworthy the comparison is (∝ cluster sample size n)
  • the baseline (n, mean, p10/p50/p90) it was measured against

Cold-start safe: if the episode has no cluster, or the cluster has no baseline
(n below the gate), `relative_scores` returns ``{}`` and callers fall back to
absolute scores — exactly the plan's guardrail.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"


def _band(percentile: float) -> str:
    """Human-readable label for where a score sits in its peer distribution."""
    if percentile < 10:
        return "bottom 10% of runs like it"
    if percentile < 25:
        return "below typical"
    if percentile <= 75:
        return "typical"
    if percentile <= 90:
        return "above typical"
    return "top 10% of runs like it"


def _percentile_of(score: float, baseline: dict) -> float:
    """Estimate the percentile of `score` within a baseline distribution.

    We only persist p10/p50/p90 + mean/stddev (not the full sample), so this is
    a piecewise-linear interpolation through the stored quantiles — accurate
    enough to say "bottom 10%" vs "typical" without storing every score.
    """
    p10 = baseline.get("p10")
    p50 = baseline.get("p50")
    p90 = baseline.get("p90")

    # Fall back to a normal approximation if quantiles are absent.
    if p10 is None or p50 is None or p90 is None:
        mean = baseline.get("mean")
        std = baseline.get("stddev")
        if mean is None or not std:
            return 50.0
        z = (score - float(mean)) / float(std)
        # Logistic CDF approximation of the normal CDF (no scipy dependency).
        import math
        return max(0.0, min(100.0, 100.0 / (1.0 + math.exp(-1.702 * z))))

    p10, p50, p90 = float(p10), float(p50), float(p90)

    def lerp(s, lo_s, hi_s, lo_p, hi_p):
        if hi_s == lo_s:
            return (lo_p + hi_p) / 2
        return lo_p + (s - lo_s) / (hi_s - lo_s) * (hi_p - lo_p)

    if score <= p10:
        # Extrapolate below p10 down to 0, clamped at 0.
        return max(0.0, lerp(score, p10 - (p50 - p10 or 1e-9), p10, 0.0, 10.0))
    if score <= p50:
        return lerp(score, p10, p50, 10.0, 50.0)
    if score <= p90:
        return lerp(score, p50, p90, 50.0, 90.0)
    return min(100.0, lerp(score, p90, p90 + (p90 - p50 or 1e-9), 90.0, 100.0))


def _confidence(n: int) -> float:
    """Map a cluster's sample size to a 0–1 confidence in the comparison.

    Saturates toward 1.0 as n grows; ~0.5 at the n=20 gate, ~0.9 by n≈100.
    """
    import math
    return round(1.0 - math.exp(-n / 40.0), 3)


def relative_scores(client, episode_id: str) -> dict:
    """Annotate an episode's scores with their peer-relative percentile.

    Returns ``{scorer: {percentile, band, confidence, score, baseline}}`` for
    every scorer that has both a score on this episode and a cluster baseline.
    Empty dict when the episode is unclustered or its cluster lacks baselines
    (callers fall back to absolute scores).
    """
    try:
        ep_resp = (
            client.table("episodes")
            .select("cluster_id")
            .eq("episode_id", episode_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        log.warning(f"relative_scores: episode lookup failed for {episode_id}: {exc}")
        return {}

    if not ep_resp.data:
        return {}
    cluster_id = ep_resp.data[0].get("cluster_id")
    if not cluster_id:
        return {}

    try:
        base_resp = (
            client.table("cluster_baselines")
            .select("scorer, n, mean, p10, p50, p90, stddev")
            .eq("cluster_id", cluster_id)
            .execute()
        )
    except Exception as exc:
        if _MISSING_TABLE in str(exc):
            return {}
        raise
    baselines = {r["scorer"]: r for r in (base_resp.data or [])}
    if not baselines:
        return {}

    score_resp = (
        client.table("episode_scores")
        .select("scorer, score")
        .eq("episode_id", episode_id)
        .execute()
    )

    out: dict[str, dict] = {}
    for row in score_resp.data or []:
        scorer = row.get("scorer")
        baseline = baselines.get(scorer)
        if baseline is None:
            continue
        try:
            score = float(row["score"])
        except (TypeError, ValueError, KeyError):
            continue
        pct = round(_percentile_of(score, baseline), 1)
        out[scorer] = {
            "score": score,
            "percentile": pct,
            "band": _band(pct),
            "confidence": _confidence(int(baseline.get("n") or 0)),
            "baseline": {
                "n": baseline.get("n"),
                "mean": baseline.get("mean"),
                "p10": baseline.get("p10"),
                "p50": baseline.get("p50"),
                "p90": baseline.get("p90"),
            },
        }
    return out
