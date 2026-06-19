"""
examples/agents/fleet/workflows/run_workflows.py

Sweep the elaborate multi-stage workflows (Phase 2A) with live in-eval
transparency (Phase 2B). Each workflow runs several live tool stages that feed
each other, ending in an LLM synthesis — recorded as a real ≥4-step AGeval
episode. With --explain, each stage's live verdict + rationale is streamed as it
runs ("watch the eval think").

Usage:
    python -m examples.agents.fleet.workflows.run_workflows
    python -m examples.agents.fleet.workflows.run_workflows --only wf.finance.ma_diligence --explain
    python -m examples.agents.fleet.workflows.run_workflows --only finance_banking
    python -m examples.agents.fleet.workflows.run_workflows --explain --cap 2.00
    python -m examples.agents.fleet.workflows.run_workflows --live-side-effects --only wf.marketing.campaign_launch --explain
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import examples.agents._common  # noqa: F401,E402  - loads .env
from examples.agents.fleet.budget_openai import BudgetExceeded, OpenAIBudgetGuard  # noqa: E402
from examples.agents.fleet.workflows import registry  # noqa: E402
from examples.agents.fleet.workflows.base import run_workflow  # noqa: E402


def _select(args):
    wfs = registry.ALL_WORKFLOWS
    if args.only:
        if args.only.startswith("wf."):
            wfs = [registry.get(args.only)]
        else:
            wfs = registry.by_vertical(args.only)
            if not wfs:
                raise SystemExit(f"unknown vertical {args.only!r}")
    return wfs


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the elaborate AGeval workflows.")
    ap.add_argument("--only", help="a workflow id (wf.*) or a vertical")
    ap.add_argument("--explain", action="store_true", help="stream the live verdict + rationale per stage")
    ap.add_argument("--cap", type=float, default=3.00, help="USD budget cap (default 3.00)")
    ap.add_argument("--live-side-effects", action="store_true",
                    help="enable real side effects (sets AGEVAL_LIVE_SIDE_EFFECTS=1)")
    ap.add_argument("--model", help="override the OpenAI model")
    args = ap.parse_args()

    if args.live_side_effects:
        os.environ["AGEVAL_LIVE_SIDE_EFFECTS"] = "1"
    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] OPENAI_API_KEY not set — workflows need a real OpenAI brain.")
        return 0

    recording = bool(os.environ.get("AGEVAL_API_KEY"))
    wfs = _select(args)

    from openai import OpenAI
    guard = OpenAIBudgetGuard(OpenAI(), usd_cap=args.cap)

    print(f"Running {len(wfs)} elaborate workflows "
          f"(cap ${args.cap:.2f}, recording={'on' if recording else 'off'}, "
          f"explain={'on' if args.explain else 'off'}, "
          f"side_effects={'on' if args.live_side_effects else 'off'}).\n")

    rows = []
    episodes = []
    stopped = False
    t0 = time.monotonic()

    for i, wf in enumerate(wfs, 1):
        try:
            ep = run_workflow(wf, explain=args.explain, client=guard, model=args.model)
        except BudgetExceeded as exc:
            print(f"[{i}/{len(wfs)}] {wf.id}: BUDGET STOP — {exc}")
            stopped = True
            break
        except Exception as exc:
            print(f"[{i}/{len(wfs)}] {wf.id}: FAIL {type(exc).__name__}: {str(exc)[:100]}")
            rows.append((wf, None))
            continue
        if not ep:
            print(f"[{i}/{len(wfs)}] {wf.id}: skip")
            continue
        rows.append((wf, ep))
        if ep.get("episode_id"):
            episodes.append(ep["episode_id"])
        if not args.explain:
            print(f"[{i}/{len(wfs)}] {wf.id}: ok  steps={ep['steps']}  ep={ep.get('episode_id') or '-'}")

    _print_complexity(rows)
    elapsed = time.monotonic() - t0
    print(f"\n{guard.report()}")
    print(f"episodes recorded: {len(episodes)}   wall-clock: {elapsed:.0f}s"
          f"{'   (stopped early on budget)' if stopped else ''}")
    if episodes and recording:
        base = os.environ.get("AGEVAL_API_URL", "http://localhost:8088")
        print(f"→ scored episodes at {base} (e.g. {episodes[0]})")
        print(f"  provenance: GET {base}/episodes/{episodes[0]}/explain")
    return 0


def _print_complexity(rows) -> None:
    print("\n=== workflow complexity (steps · tools · side-effects · framework) ===")
    by_vert = defaultdict(list)
    for wf, ep in rows:
        by_vert[wf.vertical].append((wf, ep))
    tot_steps = 0
    for vert in sorted(by_vert):
        for wf, ep in by_vert[vert]:
            steps = ep["steps"] if ep else 0
            tot_steps += steps
            se = "side-fx" if wf.fires_side_effects() else "-"
            status = "ok" if ep else "FAIL"
            print(f"  {wf.id:42s} steps={steps}  tools={len(wf.tool_names())}  {se:8s} "
                  f"[{wf.framework}] {status}")
    n_ok = sum(1 for _w, e in rows if e)
    print(f"\ntotals: workflows={len(rows)} ok={n_ok}  recorded-steps={tot_steps}")


if __name__ == "__main__":
    raise SystemExit(main())
