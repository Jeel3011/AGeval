"""
merger/merger.py

Core merge logic. Called by worker.py for each job.

What it does:
  1. Fetch the LangSmith trace for run_id
  2. If trace not ready → return "not_ready" (worker will requeue)
  3. Read episode_steps from Supabase (written by the SDK decorator)
  4. Derive outcome, total_steps, total_latency_ms from the steps
  5. Update the episodes row with the merged result
  6. Generate and store embedding in episode_embeddings

Dependencies:
  pip install langsmith supabase python-dotenv openai
"""

import os
import json
import logging
from typing import Literal

from langsmith import Client as LangSmithClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point called by worker.py
# ---------------------------------------------------------------------------
def run_merger(
    client,        # supabase client (already authenticated)
    episode_id: str,
    run_id: str,
    agent_id: str,
    task: str | None,
) -> Literal["not_ready", "done"]:
    """
    Returns "not_ready" if the LangSmith trace isn't ready yet.
    Returns "done" on success.
    Raises on any other error (worker handles retry logic).
    """

    # 1. Fetch LangSmith trace
    trace = fetch_langsmith_trace(run_id)
    if trace is None:
        return "not_ready"

    # 2. Read episode_steps from Supabase
    steps = fetch_steps(client, episode_id)

    # 3. Derive episode-level fields
    outcome          = derive_outcome(steps)
    total_steps      = len(steps)
    total_latency_ms = sum(s.get("latency_ms") or 0 for s in steps)

    # 4. Build a text summary for embedding
    summary = build_summary(episode_id, agent_id, task, steps, trace)

    # 5. Update the episodes row
    client.table("episodes").update({
        "outcome"         : outcome,
        "total_steps"     : total_steps,
        "total_latency_ms": total_latency_ms,
    }).eq("episode_id", episode_id).execute()

    log.info(f"episodes row updated: {episode_id} | outcome={outcome} | steps={total_steps}")

    # 6. Generate and store embedding
    embedding = generate_embedding(summary)
    if embedding:
        upsert_embedding(client, episode_id, embedding)
        log.info(f"Embedding stored for {episode_id}")

    return "done"


# ---------------------------------------------------------------------------
# LangSmith
# ---------------------------------------------------------------------------
def fetch_langsmith_trace(run_id: str) -> dict | None:
    """
    Fetch the run from LangSmith. Returns None if the run doesn't exist yet
    or hasn't finished (end_time is None — agent still running).
    Raises on unexpected errors.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        raise RuntimeError("LANGSMITH_API_KEY not set in environment")

    ls = LangSmithClient(api_key=api_key)

    try:
        run = ls.read_run(run_id)
    except Exception as exc:
        # LangSmith 404 = run doesn't exist yet
        if "404" in str(exc) or "not found" in str(exc).lower():
            log.info(f"LangSmith run {run_id} not found yet")
            return None
        raise

    # Run exists but hasn't finished
    if run.end_time is None:
        log.info(f"LangSmith run {run_id} still in progress (no end_time)")
        return None

    return {
        "run_id"     : str(run.id),
        "name"       : run.name,
        "start_time" : run.start_time.isoformat() if run.start_time else None,
        "end_time"   : run.end_time.isoformat()   if run.end_time   else None,
        "inputs"     : run.inputs,
        "outputs"    : run.outputs,
        "error"      : run.error,
        "run_type"   : run.run_type,
    }


# ---------------------------------------------------------------------------
# Supabase: read steps
# ---------------------------------------------------------------------------
def fetch_steps(client, episode_id: str) -> list[dict]:
    """Read all episode_steps rows for this episode, ordered by step_index."""
    resp = client.table("episode_steps") \
        .select("*") \
        .eq("episode_id", episode_id) \
        .order("step_index") \
        .execute()

    return resp.data or []


# ---------------------------------------------------------------------------
# Outcome derivation
# ---------------------------------------------------------------------------
def derive_outcome(steps: list[dict]) -> str:
    """
    Simple rule-based outcome from steps.
    You'll replace this logic with your eval scorer later.

    Rules (in order):
      - No steps at all         → "failure" (nothing ran)
      - All steps succeeded     → "success"
      - All steps failed        → "failure"
      - Mixed                   → "partial"
    """
    if not steps:
        return "failure"

    successes = sum(1 for s in steps if s.get("success"))
    failures  = len(steps) - successes

    if failures == 0:
        return "success"
    if successes == 0:
        return "failure"
    return "partial"


# ---------------------------------------------------------------------------
# Summary builder (text fed into embedding)
# ---------------------------------------------------------------------------
def build_summary(
    episode_id: str,
    agent_id: str,
    task: str | None,
    steps: list[dict],
    trace: dict,
) -> str:
    """
    Build a plain-text summary of the episode for embedding.
    Keep it dense — this is what similarity search runs against.
    """
    lines = [
        f"episode_id: {episode_id}",
        f"agent: {agent_id}",
        f"task: {task or 'unspecified'}",
        f"total steps: {len(steps)}",
        f"outcome: {derive_outcome(steps)}",
        "",
        "steps:",
    ]

    for s in steps:
        status = "ok" if s.get("success") else f"FAIL({s.get('error_category','?')})"
        reasoning = s.get("reasoning") or ""
        lines.append(
            f"  [{s['step_index']}] {s['tool_name']} → {status} "
            f"({s.get('latency_ms', 0)}ms)"
            + (f" | reasoning: {reasoning[:120]}" if reasoning else "")
        )

    if trace.get("error"):
        lines.append(f"\nlangsmith error: {trace['error']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Embedding (OpenAI)
# ---------------------------------------------------------------------------
def generate_embedding(text: str) -> list[float] | None:
    """
    Generate a 1536-dim embedding using OpenAI text-embedding-3-small.
    Returns None if OPENAI_API_KEY is not set — embedding step is skipped
    gracefully, episode still merges without it.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set — skipping embedding generation")
        return None

    try:
        from openai import OpenAI
        oc = OpenAI(api_key=api_key)
        resp = oc.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding
    except Exception as exc:
        log.error(f"Embedding generation failed: {exc}")
        return None


def upsert_embedding(client, episode_id: str, embedding: list[float]):
    """Insert or update the embedding row for this episode."""
    client.table("episode_embeddings").upsert({
        "episode_id": episode_id,
        "embedding" : embedding,
    }, on_conflict="episode_id").execute()