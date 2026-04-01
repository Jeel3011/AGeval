"""
eval/llm_judge.py

LLM-as-judge scorer. Complements the deterministic rule-based scorer in rules.py.
Where rules.py scores HOW the agent behaved (tool success rates, efficiency),
the LLM judge scores WHETHER the agent achieved its goal.

Metrics evaluated by the LLM (each 0.0–1.0):
  1. task_completion    — did the agent achieve what it was asked to do?
  2. reasoning_quality  — was the chain of thought coherent and logical?
  3. error_handling     — did the agent handle failures gracefully?
  4. output_quality     — is the final output useful and accurate?

Final score = weighted mean (configurable, default equal).

Requirements:
    OPENAI_API_KEY   — used to call gpt-4o-mini as the judge
    (or set AGEVAL_JUDGE_MODEL to use a different model)

Usage:
    from eval.llm_judge import judge_episode

    result = judge_episode(client, episode_id)
    print(result)
    # {
    #   "episode_id": "ep_...",
    #   "scorer"    : "llm_judge",
    #   "score"     : 0.78,
    #   "breakdown" : {
    #       "task_completion" : 0.9,
    #       "reasoning_quality": 0.8,
    #       "error_handling"  : 0.7,
    #       "output_quality"  : 0.7,
    #   },
    #   "judge_model": "gpt-4o-mini",
    #   "reasoning"  : "The agent successfully ...",
    # }
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "task_completion"  : 0.35,
    "reasoning_quality": 0.25,
    "error_handling"   : 0.20,
    "output_quality"   : 0.20,
}
METRIC_KEYS = list(DEFAULT_WEIGHTS.keys())

JUDGE_MODEL_DEFAULT = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def judge_episode(
    client,
    episode_id  : str,
    weights     : dict[str, float] | None = None,
    model       : str | None = None,
) -> dict:
    """
    Score one episode using an LLM judge.
    Writes result to episode_scores (scorer='llm_judge') and returns breakdown.

    Args:
        client     : Supabase client
        episode_id : episode to evaluate
        weights    : optional weight dict (must sum to 1.0)
        model      : OpenAI model to use as judge (default: gpt-4o-mini)

    Raises:
        RuntimeError if OPENAI_API_KEY is not set
        ValueError if no steps or episode found
    """
    resolved    = _resolve_weights(weights)
    judge_model = model or os.environ.get("AGEVAL_JUDGE_MODEL", JUDGE_MODEL_DEFAULT)

    episode, steps = _fetch_episode_data(client, episode_id)

    if not steps:
        raise ValueError(f"No steps found for episode_id={episode_id}. Cannot judge.")

    prompt   = _build_prompt(episode, steps)
    raw      = _call_llm(prompt, judge_model)
    parsed   = _parse_response(raw)

    breakdown = {k: parsed["scores"].get(k, 0.0) for k in METRIC_KEYS}
    score     = round(sum(breakdown[k] * resolved[k] for k in METRIC_KEYS), 4)

    result = {
        "episode_id"  : episode_id,
        "scorer"      : "llm_judge",
        "score"       : score,
        "breakdown"   : breakdown,
        "weights_used": resolved,
        "judge_model" : judge_model,
        "reasoning"   : parsed.get("reasoning", ""),
    }

    _write_score(client, result)
    return result


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
def _build_prompt(episode: dict, steps: list[dict]) -> str:
    task    = episode.get("task") or "unspecified"
    outcome = episode.get("outcome") or "unknown"

    steps_text = "\n".join(
        f"  Step {s['step_index']}: {s['tool_name']} → "
        f"{'SUCCESS' if s.get('success') else 'FAIL (' + str(s.get('error_category','?')) + ')'}"
        + (f" | reasoning: {s['reasoning'][:200]}" if s.get("reasoning") else " | no reasoning")
        + (f" | latency: {s.get('latency_ms', 0)}ms")
        for s in steps
    )

    return f"""You are an expert AI agent evaluator. Score the following agent episode.

## Episode Summary
- Task: {task}
- Outcome: {outcome}
- Total steps: {len(steps)}
- Total latency: {sum(s.get('latency_ms', 0) for s in steps)}ms

## Agent Behaviour (step-by-step)
{steps_text}

## Your Task
Score the agent on these four dimensions. Be strict and honest.

1. **task_completion** (0.0–1.0): Did the agent complete the task it was given?
   - 1.0 = fully completed
   - 0.5 = partially completed
   - 0.0 = did not attempt or completely failed

2. **reasoning_quality** (0.0–1.0): Was the reasoning coherent and logical?
   - 1.0 = clear reasoning before every tool call
   - 0.5 = some reasoning present, occasionally missing or unclear
   - 0.0 = no reasoning, or reasoning doesn't match actions

3. **error_handling** (0.0–1.0): Did the agent handle failures gracefully?
   - 1.0 = recovered from all errors, no unnecessary retries
   - 0.5 = handled some errors but not others
   - 0.0 = crashed on first error or stuck in a loop

4. **output_quality** (0.0–1.0): Is the final output useful and accurate?
   - 1.0 = excellent output, clearly answers the task
   - 0.5 = partially useful
   - 0.0 = no output or incorrect / irrelevant output

## Response Format (JSON only — no other text)
{{
  "scores": {{
    "task_completion"  : <float 0.0-1.0>,
    "reasoning_quality": <float 0.0-1.0>,
    "error_handling"   : <float 0.0-1.0>,
    "output_quality"   : <float 0.0-1.0>
  }},
  "reasoning": "<2-3 sentences explaining your overall assessment>"
}}"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------
def _call_llm(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. The LLM judge requires OpenAI access. "
            "Use eval.rules.score_episode for rule-based scoring instead."
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp   = client.chat.completions.create(
            model       = model,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.0,      # deterministic — we want consistent scores
            max_tokens  = 512,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        raise RuntimeError(f"LLM judge call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _parse_response(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM judge returned invalid JSON: {e}\nRaw: {raw[:500]}") from e

    # Clamp all scores to [0.0, 1.0]
    scores = data.get("scores", {})
    for k in METRIC_KEYS:
        if k not in scores:
            log.warning(f"LLM judge missing score for '{k}', defaulting to 0.0")
            scores[k] = 0.0
        else:
            scores[k] = max(0.0, min(1.0, float(scores[k])))

    return {
        "scores"   : scores,
        "reasoning": data.get("reasoning", ""),
    }


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------
def _resolve_weights(weights: dict[str, float] | None) -> dict[str, float]:
    if weights is None:
        return DEFAULT_WEIGHTS.copy()

    unknown = set(weights) - set(METRIC_KEYS)
    if unknown:
        raise ValueError(f"Unknown metric keys: {unknown}. Valid: {METRIC_KEYS}")

    missing = set(METRIC_KEYS) - set(weights)
    if missing:
        raise ValueError(f"Missing metric keys: {missing}. All four must be specified.")

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"Weights must sum to 1.0, got {total:.6f}")

    return weights


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------
def _fetch_episode_data(client, episode_id: str) -> tuple[dict, list[dict]]:
    ep_resp = (
        client.table("episodes")
        .select("episode_id, agent_id, task, outcome, total_steps, total_latency_ms")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep_resp.data:
        raise ValueError(f"Episode {episode_id} not found")

    steps_resp = (
        client.table("episode_steps")
        .select("step_index, tool_name, success, error_category, reasoning, latency_ms, tool_output")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    )

    return ep_resp.data[0], steps_resp.data or []


def _write_score(client, result: dict) -> None:
    """Upsert score row for scorer='llm_judge'."""
    client.table("episode_scores").upsert({
        "episode_id": result["episode_id"],
        "scorer"    : result["scorer"],
        "score"     : result["score"],
        "breakdown" : {
            **result["breakdown"],
            "judge_model": result["judge_model"],
            "reasoning"  : result["reasoning"],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="episode_id,scorer").execute()
