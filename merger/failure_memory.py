"""
merger/failure_memory.py

Failure-pattern memory — the moat (EVAL_DEPTH_AND_MEMORY_PLAN §1.4).

A library of *how this agent fails*. After an episode merges, we look at its
failing steps and fold each into a named **failure signature**: a stable bucket
of (error_category | failing tool | failure-position band). For every signature
we keep a running count, first/last-seen timestamps, a sample, and a centroid of
the error-message embeddings (reusing the existing 1536-d embedding path — no
new vendor).

Three payoffs, all enabled by this module:
  1. Recurrence tracking — "the inventory env_error signature appeared in 14 runs
     over 3 days" (lifecycle, not a one-off), via `failure_occurrences`.
  2. New-episode triage — on ingest we return the signatures this episode hit so
     callers can label it instantly ("matches known failure #7").
  3. Seeds for auto-generated regression evals (api/failures.py turns a signature
     into a golden-dataset test case so the failure can't silently return).

Everything degrades gracefully: if the `failure_memory` /
`failure_occurrences` tables are absent (schema not migrated) we log and skip,
exactly like api/datasets.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"  # PostgREST: relation not found in schema cache

# A failing step's position in the trajectory, bucketed so signatures stay
# stable across runs of slightly different length. "early/mid/late" is enough
# resolution to say *where* an agent tends to break.
_POSITION_BANDS = ("early", "mid", "late")


def _is_missing_table(exc: Exception) -> bool:
    return _MISSING_TABLE in str(exc)


def _position_band(step_index: int, total_steps: int) -> str:
    """Bucket a step's position into early / mid / late."""
    if total_steps <= 1:
        return "early"
    frac = step_index / max(total_steps - 1, 1)
    if frac < 0.34:
        return "early"
    if frac < 0.67:
        return "mid"
    return "late"


def _signature(error_category: str | None, tool_name: str | None, band: str) -> str:
    """A stable, human-readable signature key."""
    return f"{error_category or 'unknown'}|{tool_name or '?'}|{band}"


def failing_steps(steps: list[dict]) -> list[dict]:
    """Meaningful steps that failed (excludes ``llm_call`` bookkeeping)."""
    return [
        s for s in steps
        if not s.get("success") and s.get("tool_name") != "llm_call"
    ]


def _embed(text: str) -> list[float] | None:
    """Embed an error message, reusing the merger's embedding path."""
    if not text:
        return None
    from merger.merger import generate_embedding
    return generate_embedding(text)


def _merge_centroid(
    old: list[float] | None, old_n: int, new: list[float] | None
) -> list[float] | None:
    """Running mean of embeddings: incremental update of the centroid.

    Weights the existing centroid by its sample size so the centroid is the
    true mean of all error embeddings seen, without storing them all.
    """
    if new is None:
        return old
    if old is None or old_n <= 0:
        return new
    return [(o * old_n + v) / (old_n + 1) for o, v in zip(old, new)]


def _parse_vector(val) -> list[float] | None:
    """pgvector comes back as a string like '[0.1,0.2,...]'; normalise to list."""
    if val is None:
        return None
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        import ast
        try:
            return ast.literal_eval(val)
        except (ValueError, SyntaxError):
            return None
    return None


def record_failures(
    client,
    episode_id: str,
    agent_id: str,
    user_id: str | None,
    steps: list[dict],
) -> list[str]:
    """Fold an episode's failing steps into failure_memory.

    Returns the list of signature strings this episode matched/created (for
    triage). A no-op returning ``[]`` when the episode has no meaningful
    failures or when user_id is unknown (we can't scope memory without it).
    """
    if not user_id:
        return []

    fails = failing_steps(steps)
    if not fails:
        return []

    total = len(steps)
    now = datetime.now(timezone.utc).isoformat()

    # One signature can recur within a single episode (e.g. the same tool fails
    # twice). Collapse to the first occurrence per signature so we don't
    # double-count a single run against its own recurrence metric.
    by_signature: dict[str, dict] = {}
    for step in fails:
        band = _position_band(step.get("step_index", 0), total)
        sig = _signature(step.get("error_category"), step.get("tool_name"), band)
        by_signature.setdefault(sig, step)

    matched: list[str] = []
    for sig, step in by_signature.items():
        try:
            if _upsert_signature(client, user_id, agent_id, episode_id, sig, step, now):
                matched.append(sig)
        except Exception as exc:
            if _is_missing_table(exc):
                log.warning("failure_memory tables missing — run sdk/schema.sql; skipping")
                return matched
            log.warning(f"failure_memory upsert failed for {sig}: {exc}")

    if matched:
        log.info(f"failure_memory: episode {episode_id} matched {len(matched)} signature(s)")
    return matched


def _upsert_signature(
    client,
    user_id: str,
    agent_id: str,
    episode_id: str,
    signature: str,
    step: dict,
    now: str,
) -> bool:
    """Create or update a single signature row + log the occurrence.

    Returns True if the occurrence was newly recorded (so the episode counts
    toward this signature's recurrence). Raises on a missing-table error so the
    caller can short-circuit the whole batch.
    """
    error_msg = (step.get("error_message") or "").strip()

    existing_resp = (
        client.table("failure_memory")
        .select("id, occurrences, centroid")
        .eq("user_id", user_id)
        .eq("agent_id", agent_id)
        .eq("signature", signature)
        .limit(1)
        .execute()
    )
    existing = (existing_resp.data or [None])[0]

    new_emb = _embed(error_msg) if error_msg else None

    if existing:
        failure_id = existing["id"]
        old_n = existing.get("occurrences") or 0
        centroid = _merge_centroid(_parse_vector(existing.get("centroid")), old_n, new_emb)

        update = {
            "occurrences": old_n + 1,
            "last_seen": now,
        }
        if centroid is not None:
            update["centroid"] = centroid
        client.table("failure_memory").update(update).eq("id", failure_id).execute()
    else:
        insert = {
            "user_id": user_id,
            "agent_id": agent_id,
            "signature": signature,
            "label": _auto_label(signature, step),
            "occurrences": 1,
            "first_seen": now,
            "last_seen": now,
            "sample_episode_id": episode_id,
            "sample_error": error_msg[:500] or None,
        }
        if new_emb is not None:
            insert["centroid"] = new_emb
        ins_resp = client.table("failure_memory").insert(insert).execute()
        if not ins_resp.data:
            return False
        failure_id = ins_resp.data[0]["id"]

    # Log the occurrence (idempotent on (failure_id, episode_id)).
    try:
        client.table("failure_occurrences").insert({
            "failure_id": failure_id,
            "episode_id": episode_id,
            "step_index": step.get("step_index"),
            "occurred_at": now,
        }).execute()
        return True
    except Exception as exc:
        # Duplicate occurrence for this episode → already counted, not an error.
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return False
        raise


def _auto_label(signature: str, step: dict) -> str:
    """A short human-readable name for a fresh signature."""
    category, tool, band = (signature.split("|") + ["", "", ""])[:3]
    pretty_cat = {
        "env_error": "environment error",
        "agent_error": "agent error",
        "unknown": "error",
    }.get(category, category or "error")
    return f"{tool} {pretty_cat} ({band})"
