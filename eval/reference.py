"""
eval/reference.py

Reference-grounded metrics (EVAL_DEPTH_AND_MEMORY_PLAN §2.5).

Wires the DeepEval-class metrics stubbed in `ageval/llm_metrics.py`
(faithfulness / answer-relevance) into the scoring pipeline as an opt-in scorer.
They run only when the episode has a usable final output:

  • answer_relevance — input = task, output = final_output (always computable
    when both exist).
  • faithfulness     — needs retrieval context; computed only when `context` is
    supplied (e.g. for RAG agents). Skipped otherwise.

Opt-in to bound LLM spend: the worker does NOT call this by default; it's
triggered on demand via the API. Persisted as the `reference` scorer in
`episode_scores`, alongside rules / custom / llm_judge / trajectory.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _final_output_text(episode: dict) -> str:
    fo = episode.get("final_output")
    if fo is None:
        return ""
    if isinstance(fo, dict):
        # Prefer a natural-language field if present, else dump.
        for key in ("output", "answer", "text", "response", "raw"):
            if isinstance(fo.get(key), str):
                return fo[key]
        return json.dumps(fo)[:2000]
    return str(fo)[:2000]


def score_reference_metrics(client, episode_id: str, context: list[str] | None = None) -> dict | None:
    """Compute and persist reference-grounded metrics for an episode.

    Returns the result dict, or None when there's no final output to ground on.
    """
    ep_resp = (
        client.table("episodes")
        .select("task, final_output")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep_resp.data:
        return None
    episode = ep_resp.data[0]

    output = _final_output_text(episode)
    task = episode.get("task") or ""
    if not output:
        return None

    from ageval.llm_metrics import evaluate_answer_relevance, evaluate_faithfulness

    breakdown: dict[str, float] = {}
    rationales: dict[str, str] = {}

    rel = evaluate_answer_relevance(task, output)
    breakdown["answer_relevance"] = round(float(rel.get("score", 0.0)), 4)
    rationales["answer_relevance"] = rel.get("reasoning", "")

    if context:
        faith = evaluate_faithfulness(task, output, context)
        breakdown["faithfulness"] = round(float(faith.get("score", 0.0)), 4)
        rationales["faithfulness"] = faith.get("reasoning", "")

    score = round(sum(breakdown.values()) / len(breakdown), 4) if breakdown else 0.0
    result = {
        "episode_id": episode_id,
        "scorer": "reference",
        "score": score,
        "breakdown": breakdown,
        "rationales": rationales,
    }

    try:
        client.table("episode_scores").upsert({
            "episode_id": episode_id,
            "scorer": "reference",
            "score": score,
            "breakdown": {**breakdown, "_rationales": rationales},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="episode_id,scorer").execute()
    except Exception as exc:
        log.warning(f"Failed to write reference score for {episode_id}: {exc}")

    return result
