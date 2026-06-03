"""
merger/merger.py

Core merge logic. Called by worker.py for each job.

What it does:
  1. Optionally fetch the LangSmith trace (only if run_id is a real LS run ID)
  2. If LangSmith trace not ready yet → return "not_ready" (worker will requeue)
  3. Read episode_steps from Supabase (written by the SDK decorator)
  4. Derive outcome, total_steps, total_latency_ms from the steps
  5. Persist final_output from LangSmith (or last successful step) for grounded judging
  6. Update the episodes row with the merged result
  7. Generate and store embedding in episode_embeddings

LangSmith dependency:
  - COMPLETELY OPTIONAL. If LANGSMITH_API_KEY is not set, or run_id is "none"/
    "unknown"/"pending"/"", LangSmith fetch is skipped and the merger runs purely
    on step data. This is the correct path for non-LangChain agents.

Dependencies:
  pip install supabase python-dotenv openai
  pip install langsmith   # only needed if you use LangSmith
"""

import os
import logging
from typing import Literal

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IDs that signal "no LangSmith" — skip the LS fetch entirely
# ---------------------------------------------------------------------------
_NO_LANGSMITH_IDS = {"none", "unknown", "pending", "", "null"}


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

    # 1. Optionally fetch LangSmith trace
    trace: dict | None = None
    if run_id.strip().lower() in _NO_LANGSMITH_IDS:
        log.info(f"run_id='{run_id}' — skipping LangSmith fetch, using step data only")
    else:
        trace = fetch_langsmith_trace(run_id)
        if trace is None:
            return "not_ready"

    # 2. Read episode_steps from Supabase
    steps = fetch_steps(client, episode_id)

    # 3. Derive episode-level fields
    outcome          = derive_outcome(steps)
    total_steps      = len(steps)
    total_latency_ms = sum(s.get("latency_ms") or 0 for s in steps)

    # 4. Determine final_output for grounded judging
    #    Priority: LangSmith outputs > last successful step output > None
    final_output = _derive_final_output(steps, trace)

    # 5. Build a text summary for embedding
    summary = build_summary(episode_id, agent_id, task, steps, trace)

    # 6. Update the episodes row
    update_payload: dict = {
        "outcome"         : outcome,
        "total_steps"     : total_steps,
        "total_latency_ms": total_latency_ms,
    }
    if final_output is not None:
        update_payload["final_output"] = final_output

    client.table("episodes").update(update_payload).eq("episode_id", episode_id).execute()

    log.info(f"episodes row updated: {episode_id} | outcome={outcome} | steps={total_steps}")

    # 7. Generate and store embedding
    embedding = generate_embedding(summary)
    if embedding:
        upsert_embedding(client, episode_id, embedding)
        log.info(f"Embedding stored for {episode_id}")

    return "done"


# ---------------------------------------------------------------------------
# Final output derivation (for grounded LLM judging)
# ---------------------------------------------------------------------------
def _derive_final_output(steps: list[dict], trace: dict | None) -> dict | None:
    """
    Determine the final output of the episode for use in LLM judging.

    Priority order:
      1. LangSmith trace outputs (most reliable for LangChain agents)
      2. Last successful step's tool_output (fallback for all agents)
      3. None (judge will note output_quality cannot be assessed)
    """
    # Try LangSmith outputs first
    if trace and trace.get("outputs"):
        outputs = trace["outputs"]
        if isinstance(outputs, dict):
            return outputs
        return {"raw": str(outputs)}

    # Fallback: last successful step output
    for step in reversed(steps):
        if step.get("success") and step.get("tool_output") is not None:
            output = step["tool_output"]
            if isinstance(output, dict):
                return output
            return {"raw": str(output), "from_tool": step.get("tool_name")}

    return None


# ---------------------------------------------------------------------------
# LangSmith (optional)
# ---------------------------------------------------------------------------
def fetch_langsmith_trace(run_id: str) -> dict | None:
    """
    Fetch the run from LangSmith. Returns None if:
      - LANGSMITH_API_KEY is not set (graceful skip, not an error)
      - The run doesn't exist yet (agent still running / LS ingestion lag)
      - The run hasn't finished (end_time is None)
    Raises on unexpected non-404 errors.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        log.warning("LANGSMITH_API_KEY not set — skipping LangSmith trace fetch")
        return None

    try:
        from langsmith import Client as LangSmithClient
    except ImportError:
        log.warning("langsmith package not installed — skipping LangSmith trace fetch")
        return None

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
    Rule-based outcome from steps.

    Outcome is judged on the agent's *meaningful* tool work, NOT on the
    ``llm_call`` bookkeeping steps that the OpenAI/Anthropic tracers record.
    Those LLM steps almost always "succeed" (a model reply came back), so
    counting them would dilute every episode toward "partial"/"success" and
    we'd never flag a genuinely failing tool-using agent — defeating the
    point of the platform. We therefore exclude them when any real tool step
    exists, and fall back to all steps only when an episode is LLM-only.

    Rules (over the judged steps):
      - No steps at all        → "failure" (nothing ran)
      - All steps succeeded    → "success"
      - All steps failed       → "failure"
      - Mixed                  → "partial"
    """
    if not steps:
        return "failure"

    meaningful = [s for s in steps if s.get("tool_name") != "llm_call"]
    judged = meaningful or steps  # LLM-only episode → judge on what we have

    successes = sum(1 for s in judged if s.get("success"))
    failures  = len(judged) - successes

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
    trace: dict | None,
) -> str:
    """
    Build a plain-text summary of the episode for embedding.
    Keep it dense — this is what similarity search runs against.
    Works correctly whether or not LangSmith trace data is available.
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

    if trace and trace.get("error"):
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
