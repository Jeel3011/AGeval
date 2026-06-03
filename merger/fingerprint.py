"""
merger/fingerprint.py

Episodic-memory deepening (EVAL_DEPTH_AND_MEMORY_PLAN §1.1).

A *fingerprint* is a stable, content-addressed hash of the shape of a run:
the ordered sequence of meaningful tool names plus the derived outcome. Two
runs that called the same tools in the same order and ended the same way share
a fingerprint, so identically-shaped runs become O(1) groupable — the cheap
enabler for trajectory regression diffing (§2.1).

The fingerprint deliberately ignores arguments, latencies and reasoning so it
stays stable across cosmetic differences; it captures *path shape + outcome*,
which is what regression detection keys on.

`llm_call` bookkeeping steps are excluded (mirroring `derive_outcome`) so the
fingerprint reflects the agent's real tool work, not how chatty the model was.
"""

from __future__ import annotations

import hashlib


def tool_sequence(steps: list[dict]) -> list[str]:
    """The ordered list of meaningful tool names (excludes ``llm_call``).

    Falls back to all steps for an LLM-only episode, mirroring
    ``merger.merger.derive_outcome`` so the two never disagree about what
    "meaningful work" means.
    """
    ordered = sorted(steps, key=lambda s: s.get("step_index", 0))
    meaningful = [s for s in ordered if s.get("tool_name") != "llm_call"]
    judged = meaningful or ordered
    return [s.get("tool_name", "?") for s in judged]


def compute_fingerprint(steps: list[dict], outcome: str) -> str:
    """Return a stable 16-hex-char fingerprint for a run's shape + outcome.

    Empty episodes still get a deterministic fingerprint (keyed on the
    outcome alone) so they group together rather than each being unique.
    """
    seq = tool_sequence(steps)
    payload = outcome + "\n" + "\n".join(seq)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:16]
