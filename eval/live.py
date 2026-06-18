"""
eval/live.py

The Live Verdict engine — the wedge (LIVE_EVAL_WEDGE_PLAN §1).

Every other evaluation in AGeval is retrospective: a worker scores an episode
*after* the agent already shipped its answer. This module renders a verdict
**synchronously, mid-run**, so an agent can act on it before the bad output
reaches a user.

The whole game is latency. A live verdict must be fast enough to sit inside the
agent's loop, so the hot path uses ONLY memory that is already materialised —
no LLM call, no fresh clustering. Three deterministic / vector-lookup layers,
each backed by a table we already populate:

  1. Failure-signature match  — cosine of the step's error/intent embedding
     against `failure_memory.centroid`  → "matches known failure #7".
  2. Baseline outlier check    — is a numeric tool input outside the cluster's
     p10–p90 band in `cluster_baselines`? → "100x the normal charge amount".
  3. Procedural deviation      — does the tool sequence so far still match the
     golden-path prefix in `procedural_memory`? → "off the golden path".

The layers combine into a `Verdict(action, score, confidence, reasons,
suggest)`. The LLM judge is intentionally NOT in the hot path — it belongs to an
async escalation tier (a later phase); here a verdict that *wants* the judge
returns ``action="escalate"`` and lets the caller decide.

Safety stance (Phase A is shadow-first):
  • Absence of memory → ``allow``. AGeval can never make an agent *more* broken
    than it already was without a policy.
  • Cold start: signatures/baselines below their volume gate are advisory
    (``warn``) only, never ``block``.
  • Everything degrades gracefully if a memory table is absent (un-migrated DB).
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

_MISSING_TABLE = "PGRST205"

# --- tuning knobs (conservative; Phase A is shadow-mode) --------------------

# Cosine similarity at/above which a step is considered to MATCH a known failure
# signature. Embeddings are L2-ish normalised by the model; 0.82 is a tight
# match without being brittle.
FAILURE_MATCH_THRESHOLD = 0.82

# A signature must have recurred at least this many times before a live match is
# allowed to escalate past "warn" — a one-off failure isn't a pattern yet.
MIN_SIGNATURE_OCCURRENCES = 3

# How many standard deviations outside a baseline a numeric input must be before
# we call it an outlier worth warning about.
BASELINE_OUTLIER_Z = 4.0

# A cluster baseline needs this many samples before its band is trustworthy
# enough to gate on (mirrors merger.baselines.MIN_BASELINE_N).
MIN_BASELINE_N = 20

# Procedural adherence below this (the run has diverged from the golden prefix)
# is flagged. 1.0 = on path, 0.0 = nothing in common.
PROCEDURAL_ADHERENCE_FLOOR = 0.5


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
@dataclass
class Reason:
    """One human-readable factor behind a verdict, with its provenance."""
    layer: str                 # 'failure' | 'baseline' | 'procedural'
    message: str
    severity: str = "info"     # 'info' | 'warn' | 'high'
    detail: dict = field(default_factory=dict)


@dataclass
class Verdict:
    """The result of evaluating one step against live memory.

    `action` is *advice* — the SDK/policy layer decides what to do with it. In
    Phase A (no policies yet) the engine returns the raw recommended action and
    the caller (shadow mode) simply logs it.
    """
    action: str = "allow"                       # allow | warn | block | escalate
    score: float = 1.0                          # 0..1, lower = more concerning
    confidence: float = 0.0                     # 0..1, ∝ memory volume behind it
    reasons: list = field(default_factory=list) # list[Reason]
    suggest: dict | None = None                 # optional repair hint
    matched_signature_id: str | None = None
    latency_ms: int | None = None
    # Set by eval/policy.apply_policy when a live policy is active:
    policy_decision: str | None = None          # what the policy *decided*
    policy_mode: str | None = None              # 'log_only' | 'enforce'
    policy_enforced: bool = False               # was the decision actually enforced?

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = [asdict(r) if isinstance(r, Reason) else r for r in self.reasons]
        return d


# severity → recommended action ranking (worst wins)
_ACTION_RANK = {"allow": 0, "warn": 1, "escalate": 2, "block": 3}


def _worst(*actions: str) -> str:
    return max(actions, key=lambda a: _ACTION_RANK.get(a, 0))


# ---------------------------------------------------------------------------
# Vector math (in-process; the hot path never round-trips for similarity)
# ---------------------------------------------------------------------------
def _parse_vector(val):
    """pgvector returns '[0.1,0.2,...]' or a list; normalise to list[float]."""
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


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _confidence_from_n(n: int) -> float:
    """Map a sample size to 0..1 confidence (saturates ~0.9 by n≈100)."""
    return round(1.0 - math.exp(-max(n, 0) / 40.0), 3)


# ---------------------------------------------------------------------------
# Memory snapshot — pulled once, matched in-process (latency budget)
# ---------------------------------------------------------------------------
@dataclass
class MemorySnapshot:
    """A small, agent-scoped view of evaluation memory for fast live matching.

    Pulled in one cheap pass (a handful of rows per agent) so the per-step
    verdict is pure CPU. Re-fetched lazily by the caller; in a later phase the
    SDK caches this client-side for sub-10ms local verdicts.
    """
    signatures: list = field(default_factory=list)   # failure_memory rows (+parsed centroid)
    golden: dict | None = None                        # procedural_memory row for the agent
    numeric_baselines: dict = field(default_factory=dict)  # tool.field -> {mean,std,p10,p90,n}

    @property
    def empty(self) -> bool:
        return not self.signatures and not self.golden and not self.numeric_baselines


def load_snapshot(client, user_id: str, agent_id: str) -> MemorySnapshot:
    """Pull the agent's live-relevant memory in one cheap pass.

    Degrades to an empty snapshot (→ everything allowed) if any table is absent.
    """
    snap = MemorySnapshot()

    # 1. Failure signatures (the moat). Most-recurrent first; cap the pull so a
    #    noisy agent can't blow the latency budget.
    try:
        resp = (
            client.table("failure_memory")
            .select("id, signature, label, centroid, occurrences")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("occurrences", desc=True)
            .limit(50)
            .execute()
        )
        for row in resp.data or []:
            row["_centroid"] = _parse_vector(row.get("centroid"))
            snap.signatures.append(row)
    except Exception as exc:
        if _MISSING_TABLE not in str(exc):
            log.warning(f"live: failure_memory snapshot failed: {exc}")

    # 2. Golden trajectory for this agent (procedural deviation). One row keyed
    #    per cluster; we take the agent's most-sampled golden path as the prefix
    #    reference (good enough for a single-agent live check).
    try:
        resp = (
            client.table("procedural_memory")
            .select("golden_sequence, expected_steps, expected_tools, n")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("n", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            snap.golden = resp.data[0]
    except Exception as exc:
        if _MISSING_TABLE not in str(exc):
            log.warning(f"live: procedural_memory snapshot failed: {exc}")

    # 3. Numeric input baselines (the outlier layer) are mined by a dedicated
    #    job that profiles per-(tool, field) input distributions — `tool_input`
    #    stats, distinct from `cluster_baselines` which holds *score* stats.
    #    That miner lands in Phase B; until then this stays empty and the
    #    outlier layer is dormant (not broken). Populate via `numeric_baselines`
    #    if a caller has its own source.
    snap.numeric_baselines = _load_numeric_baselines(client, user_id, agent_id)

    return snap


def _load_numeric_baselines(client, user_id: str, agent_id: str) -> dict:
    """Load per-(tool, field) numeric input baselines if the table exists.

    Returns ``{"tool.field": {mean, std, p10, p90, n}}``. The
    `tool_input_baselines` table is created by the Phase-B miner; absent it,
    this returns ``{}`` and the outlier layer simply doesn't fire.
    """
    try:
        resp = (
            client.table("tool_input_baselines")
            .select("tool_name, field, mean, std, p10, p90, n")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .execute()
        )
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for r in resp.data or []:
        key = f"{r.get('tool_name')}.{r.get('field')}"
        out[key] = {k: r.get(k) for k in ("mean", "std", "p10", "p90", "n")}
    return out


# ---------------------------------------------------------------------------
# The three layers
# ---------------------------------------------------------------------------
def _check_failure_signature(
    snap: MemorySnapshot, step_embedding: list[float] | None
) -> tuple[Reason | None, str | None]:
    """Layer 1: does this step look like a known failure mode?

    Returns (reason, matched_signature_id). Only signatures that have recurred
    >= MIN_SIGNATURE_OCCURRENCES are allowed to recommend more than a warning.
    """
    if not step_embedding or not snap.signatures:
        return None, None

    best_sim = 0.0
    best = None
    for sig in snap.signatures:
        centroid = sig.get("_centroid")
        if not centroid:
            continue
        sim = _cosine(step_embedding, centroid)
        if sim > best_sim:
            best_sim, best = sim, sig

    if best is None or best_sim < FAILURE_MATCH_THRESHOLD:
        return None, None

    occ = int(best.get("occurrences") or 0)
    severity = "high" if occ >= MIN_SIGNATURE_OCCURRENCES else "warn"
    label = best.get("label") or best.get("signature")
    reason = Reason(
        layer="failure",
        message=f"matches known failure '{label}' (seen {occ}x, similarity {best_sim:.2f})",
        severity=severity,
        detail={"similarity": round(best_sim, 4), "occurrences": occ,
                "signature": best.get("signature")},
    )
    return reason, best.get("id")


def _check_baseline_outlier(
    snap: MemorySnapshot, tool_name: str, tool_input
) -> Reason | None:
    """Layer 2: is a numeric input wildly outside the peer band for this tool?

    Pure arithmetic against `cluster_baselines`-derived numeric ranges. Only
    fires for fields with a trustworthy baseline (n >= MIN_BASELINE_N).
    """
    if not snap.numeric_baselines or not isinstance(tool_input, dict):
        return None

    for field_name, value in tool_input.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        key = f"{tool_name}.{field_name}"
        base = snap.numeric_baselines.get(key)
        if not base or (base.get("n") or 0) < MIN_BASELINE_N:
            continue
        mean = base.get("mean")
        std = base.get("std") or 0.0
        if mean is None or std <= 0:
            continue
        z = abs(value - mean) / std
        if z >= BASELINE_OUTLIER_Z:
            return Reason(
                layer="baseline",
                message=(f"{key}={value} is {z:.1f}σ outside the normal range "
                         f"(typical ≈ {mean:.4g}, p10–p90 "
                         f"{base.get('p10')}–{base.get('p90')})"),
                severity="high",
                detail={"field": key, "value": value, "z": round(z, 2),
                        "mean": mean, "p10": base.get("p10"), "p90": base.get("p90")},
            )
    return None


def _check_procedural_deviation(
    snap: MemorySnapshot, tools_so_far: list[str]
) -> Reason | None:
    """Layer 3: has the run wandered off the golden path prefix?

    Compares the tools seen so far against the same-length prefix of the golden
    sequence via the existing adherence (edit-distance) metric.
    """
    if not snap.golden or not tools_so_far:
        return None
    golden_seq = snap.golden.get("golden_sequence") or []
    if not golden_seq:
        return None

    from eval.trajectory import adherence

    prefix = golden_seq[: len(tools_so_far)]
    score = adherence(tools_so_far, prefix)
    if score >= PROCEDURAL_ADHERENCE_FLOOR:
        return None

    expected_next = golden_seq[len(tools_so_far) - 1] if len(tools_so_far) <= len(golden_seq) else None
    return Reason(
        layer="procedural",
        message=(f"off the golden path (prefix adherence {score:.2f}); "
                 f"expected sequence so far ≈ {prefix}"),
        severity="warn",
        detail={"adherence": score, "expected_prefix": prefix,
                "expected_next": expected_next, "golden_n": snap.golden.get("n")},
    )


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------
def evaluate_step(
    snap: MemorySnapshot,
    *,
    tool_name: str,
    tool_input=None,
    step_embedding: list[float] | None = None,
    tools_so_far: list[str] | None = None,
) -> Verdict:
    """Render a live verdict for a single step against a memory snapshot.

    This is pure CPU (no DB, no LLM) so it can sit in the agent's loop. The
    caller is responsible for producing `step_embedding` (cheap, cached) and the
    running `tools_so_far` list.

    Returns a `Verdict`. With an empty snapshot (cold start / un-migrated DB)
    the verdict is always ``allow`` with confidence 0 — fail-open by design.
    """
    reasons: list[Reason] = []
    matched_sig_id: str | None = None
    confidences: list[float] = []

    if snap.empty:
        return Verdict(action="allow", score=1.0, confidence=0.0)

    fail_reason, matched_sig_id = _check_failure_signature(snap, step_embedding)
    if fail_reason:
        reasons.append(fail_reason)
        # Confidence in this layer ∝ how often the signature has recurred.
        confidences.append(_confidence_from_n(fail_reason.detail.get("occurrences", 0)))

    base_reason = _check_baseline_outlier(snap, tool_name, tool_input)
    if base_reason:
        reasons.append(base_reason)
        confidences.append(_confidence_from_n(base_reason.detail.get("n", 0)
                                              if "n" in base_reason.detail else MIN_BASELINE_N))

    proc_reason = _check_procedural_deviation(snap, tools_so_far or [])
    if proc_reason:
        reasons.append(proc_reason)
        confidences.append(_confidence_from_n(proc_reason.detail.get("golden_n", 0)))

    if not reasons:
        return Verdict(action="allow", score=1.0, confidence=0.0)

    # Score: start at 1.0, dock per concern by severity. High-severity concerns
    # bite harder. Clamped to [0, 1].
    penalty = 0.0
    for r in reasons:
        penalty += {"info": 0.1, "warn": 0.25, "high": 0.5}.get(r.severity, 0.1)
    score = round(max(0.0, 1.0 - penalty), 4)

    # Recommended action (advice). The hot path NEVER blocks on its own in
    # Phase A — a 'high' concern recommends 'escalate' (route to async judge /
    # human), and only the policy layer (Phase B) can promote that to 'block'.
    action = "allow"
    if any(r.severity == "high" for r in reasons):
        action = "escalate"
    elif reasons:
        action = "warn"

    confidence = round(max(confidences) if confidences else 0.0, 3)

    # Repair hint: if a baseline outlier fired, suggest the typical value.
    suggest = None
    for r in reasons:
        if r.layer == "baseline" and "mean" in r.detail:
            suggest = {r.detail["field"].split(".", 1)[-1]: r.detail["mean"]}
            break

    return Verdict(
        action=action,
        score=score,
        confidence=confidence,
        reasons=reasons,
        suggest=suggest,
        matched_signature_id=matched_sig_id,
    )
