"""
examples/agents/_harness.py

Offline scoring harness for the example agents. Runs an agent's
`build_and_run()`, captures the steps it recorded into its AgentSession
(without needing a server or DB), derives the episode summary, and computes
AGeval's metrics on those steps.

This is what lets us assert — repeatably — that AGeval:
  * scores well-behaved agents high,
  * scores the intentionally-failing agents (20, 21) low, and
  * is CONSISTENT across repeated runs and across LangGraph state regimes.

Nothing here mocks AGeval's scoring: it calls the real metric functions from
`ageval.metrics` on the real recorded steps. Only the network sink is stubbed.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

import ageval.session as _session
from ageval import metrics as _metrics


def _derive_outcome(steps: list[dict]) -> str:
    """Use the *production* outcome rule (merger.derive_outcome) so offline
    assertions reflect exactly what the deployed pipeline would label. We import
    it rather than re-implement it, to guarantee they never drift apart."""
    from merger.merger import derive_outcome
    return derive_outcome(steps)


def run_agent_capture(path: str) -> dict[str, Any]:
    """Run one agent file's build_and_run() and capture its recorded steps.

    Returns {"steps", "episode", "metrics", "outcome", "final"} or
    {"skipped": True} if the agent couldn't run (e.g. missing key/framework).
    """
    captured: dict[str, Any] = {"steps": []}

    # Stub the network sink so nothing is posted, but keep step recording intact.
    orig_post = _session._post
    orig_record = _session.AgentSession.record_step

    def fake_post(*_a, **_k):
        return {}

    def record_spy(self, *args, **kwargs):
        idx = orig_record(self, *args, **kwargs)
        # The step we just appended is the last one in the buffer.
        if self._steps:
            captured["steps"].append(dict(self._steps[-1]))
        return idx

    _session._post = fake_post
    _session.AgentSession.record_step = record_spy
    os.environ.setdefault("AGEVAL_API_KEY", "harness-offline")

    try:
        spec = importlib.util.spec_from_file_location("harness_" + os.path.basename(path)[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        result = mod.build_and_run() or {}
    finally:
        _session._post = orig_post
        _session.AgentSession.record_step = orig_record

    steps = captured["steps"]
    if not result or not steps:
        return {"skipped": True, "final": (result or {}).get("final_content")}

    outcome = _derive_outcome(steps)
    episode = {
        "episode_id": result.get("episode_id"),
        "outcome": outcome,
        "total_steps": len(steps),
        "total_latency_ms": sum((s.get("latency_ms") or 0) for s in steps),
    }
    scored = {m["name"]: _metrics.get_metric(m["name"])(steps, episode)
              for m in _metrics.list_metrics()}
    return {
        "steps": steps,
        "episode": episode,
        "metrics": scored,
        "outcome": outcome,
        "final": result.get("final_content"),
    }


def repeat(path: str, n: int) -> list[dict[str, Any]]:
    """Run an agent n times; return the per-run capture dicts (skips dropped)."""
    runs = []
    for _ in range(n):
        r = run_agent_capture(path)
        if not r.get("skipped"):
            runs.append(r)
    return runs


def summarize(runs: list[dict[str, Any]], keys: list[str]) -> dict[str, dict[str, float]]:
    """Min/max/mean for selected metric keys across runs — used to assert
    consistency (small spread) and reliability (correct level)."""
    out: dict[str, dict[str, float]] = {}
    for k in keys:
        vals = [float(r["metrics"][k]) for r in runs if k in r["metrics"]]
        if not vals:
            continue
        out[k] = {"min": min(vals), "max": max(vals),
                  "mean": round(sum(vals) / len(vals), 4), "spread": round(max(vals) - min(vals), 4)}
    return out
