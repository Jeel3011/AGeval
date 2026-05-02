"""
ageval/metrics.py

Custom metric registry for domain-specific evaluation.

The built-in rule-based scorer (eval/rules.py) covers universal metrics like
success_rate and efficiency. But real-world agents need domain-specific metrics:
  - "Did the travel agent pick the cheapest flight?"
  - "Did the coding agent's solution pass all tests?"
  - "Did the customer support agent resolve the ticket?"

This module lets users define and register their own metrics that run
alongside the built-in ones.

Usage:
    from ageval.metrics import register_metric, score_with_custom_metrics

    @register_metric("cost_efficiency", weight=0.3)
    def cost_efficiency(steps: list[dict], episode: dict) -> float:
        # Your custom logic — return 0.0 to 1.0
        outputs = [s.get("tool_output", {}) for s in steps if s.get("success")]
        cheapest = min(o.get("price", float("inf")) for o in outputs)
        return 1.0 if cheapest < 500 else cheapest / 1000

    # Score an episode with built-in + custom metrics:
    result = score_with_custom_metrics(client, episode_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric Registry
# ---------------------------------------------------------------------------
MetricFn = Callable[[list[dict], dict], float]

_registry: dict[str, dict[str, Any]] = {}


def register_metric(
    name: str,
    weight: float = 0.0,
    description: str = "",
) -> Callable[[MetricFn], MetricFn]:
    """
    Decorator to register a custom evaluation metric.

    Args:
        name: Unique metric name (e.g. "cost_efficiency")
        weight: Weight in the composite score (0.0 = not included in composite)
        description: Human-readable description

    The decorated function must have signature:
        def my_metric(steps: list[dict], episode: dict) -> float

    Where:
        - steps: list of step dicts from episode_steps
        - episode: the episode dict (has agent_id, task, outcome, etc.)
        - returns: float between 0.0 and 1.0
    """
    def decorator(fn: MetricFn) -> MetricFn:
        if name in _registry:
            log.warning(f"[ageval] Overwriting metric '{name}'")
        _registry[name] = {
            "fn": fn,
            "weight": weight,
            "description": description or fn.__doc__ or "",
        }
        return fn
    return decorator


def unregister_metric(name: str) -> bool:
    """Remove a registered metric. Returns True if it existed."""
    return _registry.pop(name, None) is not None


def list_metrics() -> list[dict]:
    """List all registered custom metrics."""
    return [
        {"name": k, "weight": v["weight"], "description": v["description"]}
        for k, v in _registry.items()
    ]


def get_metric(name: str) -> Optional[MetricFn]:
    """Get a metric function by name."""
    entry = _registry.get(name)
    return entry["fn"] if entry else None


# ---------------------------------------------------------------------------
# Built-in metrics that users can mix with custom ones
# ---------------------------------------------------------------------------
@register_metric(
    "tool_diversity",
    weight=0.0,
    description="Measures how many unique tools the agent used vs total steps",
)
def tool_diversity(steps: list[dict], episode: dict) -> float:
    """Higher score = agent used a wider variety of tools."""
    if not steps:
        return 0.0
    unique_tools = len(set(s.get("tool_name", "") for s in steps))
    return round(min(1.0, unique_tools / max(len(steps), 1)), 4)


@register_metric(
    "latency_budget",
    weight=0.0,
    description="Penalizes episodes that took too long (>30s total)",
)
def latency_budget(steps: list[dict], episode: dict) -> float:
    """1.0 if under 5s, decays to 0.0 at 60s."""
    total_ms = sum(s.get("latency_ms", 0) for s in steps)
    total_s = total_ms / 1000
    if total_s <= 5:
        return 1.0
    if total_s >= 60:
        return 0.0
    return round(1.0 - (total_s - 5) / 55, 4)


@register_metric(
    "error_recovery_speed",
    weight=0.0,
    description="How quickly the agent recovers after an error (fewer steps = better)",
)
def error_recovery_speed(steps: list[dict], episode: dict) -> float:
    """1.0 if immediate recovery, decays with recovery distance."""
    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))
    error_indices = [
        i for i, s in enumerate(sorted_steps)
        if not s.get("success") and s.get("error_category") == "env_error"
    ]
    if not error_indices:
        return 1.0  # No errors to recover from

    recovery_distances = []
    for err_idx in error_indices:
        for j in range(err_idx + 1, len(sorted_steps)):
            if sorted_steps[j].get("success"):
                recovery_distances.append(j - err_idx)
                break
        else:
            recovery_distances.append(len(sorted_steps))  # Never recovered

    if not recovery_distances:
        return 0.0

    avg_distance = sum(recovery_distances) / len(recovery_distances)
    # 1 step = 1.0, 5+ steps = 0.0
    return round(max(0.0, 1.0 - (avg_distance - 1) / 4), 4)


# ---------------------------------------------------------------------------
# Scoring function that combines built-in + custom metrics
# ---------------------------------------------------------------------------
def score_with_custom_metrics(
    client,
    episode_id: str,
    metric_names: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Score an episode using custom metrics.

    Args:
        client: Supabase client
        episode_id: Episode to score
        metric_names: Which custom metrics to run (default: all registered)
        weights: Override weights (must sum to 1.0 if provided)

    Returns:
        Dict with keys: episode_id, scorer, score, breakdown
    """
    # Fetch episode data
    ep_resp = (
        client.table("episodes")
        .select("*")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep_resp.data:
        raise ValueError(f"Episode {episode_id} not found")

    steps_resp = (
        client.table("episode_steps")
        .select("*")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    )

    episode = ep_resp.data[0]
    steps = steps_resp.data or []

    if not steps:
        raise ValueError(f"No steps found for episode {episode_id}")

    # Determine which metrics to run
    names = metric_names or list(_registry.keys())
    active_metrics = {n: _registry[n] for n in names if n in _registry}

    if not active_metrics:
        raise ValueError(
            f"No registered metrics found. Register metrics with @register_metric."
        )

    # Run each metric
    breakdown = {}
    for name, entry in active_metrics.items():
        try:
            value = entry["fn"](steps, episode)
            breakdown[name] = round(max(0.0, min(1.0, float(value))), 4)
        except Exception as exc:
            log.error(f"Custom metric '{name}' failed for {episode_id}: {exc}")
            breakdown[name] = 0.0

    # Compute composite score
    if weights:
        # User-provided weights
        total_weight = sum(weights.get(k, 0) for k in breakdown)
        if total_weight > 0:
            score = sum(
                breakdown[k] * weights.get(k, 0) for k in breakdown
            ) / total_weight
        else:
            score = sum(breakdown.values()) / len(breakdown)
    else:
        # Use registered weights; if all zero, equal weight
        total_weight = sum(active_metrics[k]["weight"] for k in breakdown)
        if total_weight > 0:
            score = sum(
                breakdown[k] * active_metrics[k]["weight"] for k in breakdown
            ) / total_weight
        else:
            score = sum(breakdown.values()) / len(breakdown)

    score = round(score, 4)

    result = {
        "episode_id": episode_id,
        "scorer": "custom",
        "score": score,
        "breakdown": breakdown,
    }

    # Write to episode_scores
    try:
        client.table("episode_scores").upsert(
            {
                "episode_id": episode_id,
                "scorer": "custom",
                "score": score,
                "breakdown": breakdown,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="episode_id,scorer",
        ).execute()
    except Exception as exc:
        log.warning(f"Failed to write custom score for {episode_id}: {exc}")

    return result
