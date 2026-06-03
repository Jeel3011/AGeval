"""
api/regression.py

Trajectory regression detection (EVAL_DEPTH_AND_MEMORY_PLAN §2.1 — flagship).

Compares an agent's recent behaviour against an earlier baseline window and
surfaces *what changed*, not just that the average score moved:

  • score_deltas    — mean change per scorer (rules / custom / llm_judge /
                      trajectory), with before/after means.
  • step_drift      — change in average meaningful-step count.
  • outcome_shift   — success/partial/failure rate change.
  • new_failures    — failure signatures present in the recent window but not the
                      baseline window (regressions the agent didn't used to hit).
  • new_trajectories — episode fingerprints (path shapes) that appear only in the
                      recent window (behaviour that changed shape).

The data model has no explicit agent-version column, so "from"/"to" define a
*time boundary*: episodes at/after `to_ts` are the "after" cohort and episodes in
[from_ts, to_ts) are the baseline. Both default to a 7-day window vs the prior
7 days — the same windowing the clustering drift metric uses.

Pure `compute_regression(...)` does the math over plain dicts so it's testable
against the in-memory fake; the FastAPI endpoint is a thin DB-fetch wrapper.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _episode_ts(ep: dict) -> datetime | None:
    return _parse_ts(ep.get("created_at"))


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def compute_regression(
    episodes: list[dict],
    scores_by_episode: dict[str, dict[str, float]],
    failures_by_window: dict[str, set[str]],
    from_ts: datetime,
    to_ts: datetime,
) -> dict:
    """Diff the 'after' cohort (>= to_ts) against the baseline [from_ts, to_ts).

    Args:
        episodes:           episode dicts with episode_id, created_at, outcome,
                            total_steps, episode_fingerprint.
        scores_by_episode:  episode_id -> {scorer: score}.
        failures_by_window: {"baseline": {signatures...}, "after": {signatures...}}.
        from_ts, to_ts:     window boundaries (tz-aware).
    """
    baseline, after = [], []
    for ep in episodes:
        ts = _episode_ts(ep)
        if ts is None:
            continue
        if ts >= to_ts:
            after.append(ep)
        elif ts >= from_ts:
            baseline.append(ep)

    def cohort_scores(cohort: list[dict]) -> dict[str, list[float]]:
        acc: dict[str, list[float]] = {}
        for ep in cohort:
            for scorer, val in scores_by_episode.get(ep["episode_id"], {}).items():
                acc.setdefault(scorer, []).append(val)
        return acc

    base_scores = cohort_scores(baseline)
    after_scores = cohort_scores(after)

    score_deltas = {}
    for scorer in sorted(set(base_scores) | set(after_scores)):
        b, a = _mean(base_scores.get(scorer, [])), _mean(after_scores.get(scorer, []))
        delta = round(a - b, 4) if (a is not None and b is not None) else None
        score_deltas[scorer] = {"baseline": b, "after": a, "delta": delta}

    def avg_steps(cohort):
        vals = [ep.get("total_steps") or 0 for ep in cohort]
        return _mean([float(v) for v in vals])

    def outcome_rates(cohort):
        n = len(cohort) or 1
        c = Counter(ep.get("outcome") for ep in cohort)
        return {o: round(c.get(o, 0) / n, 4) for o in ("success", "partial", "failure")}

    base_fp = {ep.get("episode_fingerprint") for ep in baseline if ep.get("episode_fingerprint")}
    after_fp = Counter(
        ep.get("episode_fingerprint") for ep in after if ep.get("episode_fingerprint")
    )
    new_trajectories = sorted(fp for fp in after_fp if fp not in base_fp)

    base_fails = failures_by_window.get("baseline", set())
    after_fails = failures_by_window.get("after", set())
    new_failures = sorted(after_fails - base_fails)

    return {
        "window": {
            "from": from_ts.isoformat(),
            "to": to_ts.isoformat(),
            "baseline_n": len(baseline),
            "after_n": len(after),
        },
        "score_deltas": score_deltas,
        "step_drift": {
            "baseline": avg_steps(baseline),
            "after": avg_steps(after),
        },
        "outcome_shift": {
            "baseline": outcome_rates(baseline),
            "after": outcome_rates(after),
        },
        "new_failures": new_failures,
        "new_trajectories": new_trajectories,
        "regressed": any(
            (d["delta"] is not None and d["delta"] < -0.05) for d in score_deltas.values()
        ) or bool(new_failures),
    }


def default_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Last-7-days vs prior-7-days: returns (from_ts, to_ts)."""
    now = now or datetime.now(timezone.utc)
    to_ts = now - timedelta(days=7)
    from_ts = now - timedelta(days=14)
    return from_ts, to_ts


def fetch_and_compute(db, user_id: str, agent_id: str, from_raw: str | None, to_raw: str | None) -> dict:
    """DB-backed entry point used by the endpoint. Scopes to the user's agent."""
    from_ts = _parse_ts(from_raw)
    to_ts = _parse_ts(to_raw)
    if from_ts is None or to_ts is None:
        d_from, d_to = default_window()
        from_ts = from_ts or d_from
        to_ts = to_ts or d_to

    def _fetch(cols: str):
        return (
            db.table("episodes")
            .select(cols)
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .gte("created_at", from_ts.isoformat())
            .execute()
        )

    # episode_fingerprint is an optional column (added by the §1.1 migration).
    # If the schema hasn't been migrated yet, retry without it so the rest of
    # the regression diff (scores, steps, failures) still works.
    try:
        eps_resp = _fetch("episode_id, created_at, outcome, total_steps, episode_fingerprint")
    except Exception as exc:
        if "episode_fingerprint" in str(exc) or "42703" in str(exc):
            log.info("episode_fingerprint column absent — run sdk/schema.sql; regression without trajectory-shape diff")
            eps_resp = _fetch("episode_id, created_at, outcome, total_steps")
        else:
            raise
    episodes = eps_resp.data or []
    ep_ids = [e["episode_id"] for e in episodes]

    scores_by_episode: dict[str, dict[str, float]] = {}
    for i in range(0, len(ep_ids), 100):
        batch = ep_ids[i : i + 100]
        if not batch:
            continue
        sresp = db.table("episode_scores").select("episode_id, scorer, score").in_("episode_id", batch).execute()
        for r in sresp.data or []:
            try:
                scores_by_episode.setdefault(r["episode_id"], {})[r["scorer"]] = float(r["score"])
            except (TypeError, ValueError, KeyError):
                continue

    # Failure signatures per window, via failure_occurrences → failure_memory.
    failures_by_window = _failures_by_window(db, ep_ids, episodes, from_ts, to_ts)

    return compute_regression(episodes, scores_by_episode, failures_by_window, from_ts, to_ts)


def _failures_by_window(db, ep_ids, episodes, from_ts, to_ts) -> dict[str, set[str]]:
    """Bucket failure signatures into baseline/after by their episode's window."""
    result = {"baseline": set(), "after": set()}
    if not ep_ids:
        return result

    window_of = {}
    for ep in episodes:
        ts = _episode_ts(ep)
        if ts is None:
            continue
        window_of[ep["episode_id"]] = "after" if ts >= to_ts else "baseline"

    try:
        occ_rows = []
        for i in range(0, len(ep_ids), 100):
            batch = ep_ids[i : i + 100]
            resp = db.table("failure_occurrences").select("failure_id, episode_id").in_("episode_id", batch).execute()
            occ_rows.extend(resp.data or [])
        if not occ_rows:
            return result

        fids = list({r["failure_id"] for r in occ_rows})
        sig_of = {}
        for i in range(0, len(fids), 100):
            batch = fids[i : i + 100]
            fresp = db.table("failure_memory").select("id, signature").in_("id", batch).execute()
            for r in fresp.data or []:
                sig_of[r["id"]] = r["signature"]

        for r in occ_rows:
            win = window_of.get(r["episode_id"])
            sig = sig_of.get(r["failure_id"])
            if win and sig:
                result[win].add(sig)
    except Exception as exc:
        if "PGRST205" not in str(exc):
            log.warning(f"failure window bucketing failed: {exc}")
    return result
