"""
merger/input_baselines.py

Tool-input baselines — what a *normal tool input* looks like
(LIVE_EVAL_WEDGE_PLAN §1, the baseline-outlier layer of eval/live.py).

The live verdict's outlier layer asks "is this numeric tool input wildly outside
the normal range?" — e.g. a `charge_card` amount 100× the usual. Answering that
needs per-(tool, field) *input* distributions, which `cluster_baselines` (score
stats) doesn't hold. This module mines them.

For each (agent, tool, numeric field) we profile the values seen in **successful**
steps and persist mean/std/p10/p50/p90 into `tool_input_baselines`. Only fields
with enough samples are kept (cold-start guard), so the live layer never flags an
outlier off a handful of runs.

Runs per agent inside the clustering job (service_role). Degrades gracefully: a
missing table or no numeric inputs → log + skip, clustering still completes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from merger.baselines import _distribution

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

# Need this many successful values for a (tool, field) before its baseline is
# trustworthy enough for the live outlier layer to gate on.
MIN_INPUT_N = 20


def _numeric_fields(tool_input) -> dict[str, float]:
    """Flatten a step's tool_input into its top-level numeric fields.

    Bools are excluded (a bool is an int subclass but not a magnitude). Nested
    structures are ignored — we profile flat scalar args, which is what the
    live layer checks.
    """
    out: dict[str, float] = {}
    if not isinstance(tool_input, dict):
        return out
    for k, v in tool_input.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def mine_input_baselines(client, user_id: str, agent_id: str) -> int:
    """Mine and persist numeric tool-input baselines for one agent.

    Pulls this agent's episode_ids, then their successful steps in batches, and
    profiles each numeric tool-input field. A portable two-step approach (no
    PostgREST embedded-join dependency). Returns the number of (tool, field)
    baseline rows written. Never raises on a missing table.
    """
    try:
        ep_resp = (
            client.table("episodes")
            .select("episode_id")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .execute()
        )
    except Exception:
        return 0
    ep_ids = [r["episode_id"] for r in (ep_resp.data or []) if r.get("episode_id")]
    if not ep_ids:
        return 0

    values: dict[tuple[str, str], list[float]] = {}
    for i in range(0, len(ep_ids), 100):
        batch = ep_ids[i : i + 100]
        try:
            resp = (
                client.table("episode_steps")
                .select("tool_name, tool_input, success")
                .in_("episode_id", batch)
                .eq("success", True)
                .execute()
            )
        except Exception:
            continue
        for r in resp.data or []:
            tool = r.get("tool_name")
            if not tool or tool == "llm_call":
                continue
            for field, val in _numeric_fields(r.get("tool_input")).items():
                values.setdefault((tool, field), []).append(val)

    return _persist(client, user_id, agent_id, values)


def _persist(client, user_id: str, agent_id: str, values: dict) -> int:
    """Upsert a baseline row per (tool, field) that clears MIN_INPUT_N."""
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for (tool, field), vals in values.items():
        if len(vals) < MIN_INPUT_N:
            continue
        dist = _distribution(vals)  # {n, mean, p10, p50, p90, stddev}
        row = {
            "user_id": user_id,
            "agent_id": agent_id,
            "tool_name": tool,
            "field": field,
            "n": dist["n"],
            "mean": dist["mean"],
            "std": dist["stddev"],
            "p10": dist["p10"],
            "p50": dist["p50"],
            "p90": dist["p90"],
            "updated_at": now,
        }
        try:
            client.table("tool_input_baselines").upsert(
                row, on_conflict="user_id,agent_id,tool_name,field"
            ).execute()
            written += 1
        except Exception as exc:
            if _MISSING_TABLE in str(exc):
                log.warning("tool_input_baselines table missing — run sdk/schema.sql; skipping")
                return written
            log.warning(f"tool_input_baselines upsert failed ({tool}.{field}): {exc}")

    if written:
        log.info(f"tool_input_baselines: wrote {written} baseline(s) for agent {agent_id}")
    return written
