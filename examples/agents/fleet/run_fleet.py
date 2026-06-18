"""
examples/agents/fleet/run_fleet.py

Sweep the real-agent fleet end-to-end and prove AGeval scores real production
traffic. Each agent runs a real OpenAI brain against live external APIs
(real_tools.py) and optionally real side effects (sideeffects.py); every run
is recorded as a scored AGeval episode (when an AGEVAL_API_KEY is configured).

Safety rails:
  * One shared `OpenAIBudgetGuard` caps total spend (default $3.00). The sweep
    stops early and reports spend rather than overspending.
  * Per-host rate limiting + backoff live in the polite HTTP client, so the
    live APIs are called politely no matter how many agents run.
  * Side effects are off unless --live-side-effects (sets AGEVAL_LIVE_SIDE_EFFECTS=1).

Usage:
    python -m examples.agents.fleet.run_fleet                 # whole fleet, $3 cap
    python -m examples.agents.fleet.run_fleet --only finance_banking
    python -m examples.agents.fleet.run_fleet --only finance_banking.credit_10k
    python -m examples.agents.fleet.run_fleet --sample 1      # ~1 agent per vertical
    python -m examples.agents.fleet.run_fleet --cap 0.50 --live-side-effects
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import examples.agents._common  # noqa: F401,E402  - loads .env
from examples.agents.fleet import registry  # noqa: E402
from examples.agents.fleet.budget_openai import BudgetExceeded, OpenAIBudgetGuard  # noqa: E402
from examples.agents.fleet.factory import build_and_run  # noqa: E402


def _select(args) -> list:
    specs = registry.ALL_SPECS
    if args.only:
        if "." in args.only:
            specs = [registry.get(args.only)]
        else:
            specs = registry.by_vertical(args.only)
            if not specs:
                raise SystemExit(f"unknown vertical {args.only!r}; "
                                 f"choose from {registry.verticals()}")
    if args.sample:
        # ~N agents per vertical, preserving order.
        per: dict[str, int] = defaultdict(int)
        picked = []
        for s in specs:
            if per[s.vertical] < args.sample:
                picked.append(s)
                per[s.vertical] += 1
        specs = picked
    return specs


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the real AGeval agent fleet.")
    ap.add_argument("--only", help="a vertical (e.g. finance_banking) or a single spec id")
    ap.add_argument("--sample", type=int, metavar="N", help="run ~N agents per vertical")
    ap.add_argument("--cap", type=float, default=3.00, help="USD budget cap (default 3.00)")
    ap.add_argument("--live-side-effects", action="store_true",
                    help="enable real side effects (sets AGEVAL_LIVE_SIDE_EFFECTS=1)")
    ap.add_argument("--model", help="override the OpenAI model for every agent")
    args = ap.parse_args()

    if args.live_side_effects:
        os.environ["AGEVAL_LIVE_SIDE_EFFECTS"] = "1"

    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] OPENAI_API_KEY not set — the fleet needs a real OpenAI brain.")
        return 0

    recording = bool(os.environ.get("AGEVAL_API_KEY"))
    specs = _select(args)

    from openai import OpenAI
    guard = OpenAIBudgetGuard(OpenAI(), usd_cap=args.cap)

    print(f"Running {len(specs)} real agents across "
          f"{len({s.vertical for s in specs})} verticals "
          f"(cap ${args.cap:.2f}, recording={'on' if recording else 'off'}, "
          f"side_effects={'on' if args.live_side_effects else 'off'}).\n")

    # cell = (vertical, framework) -> {"ok","fail","skip","live_data"}
    matrix: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"ok": 0, "fail": 0, "skip": 0, "live_data": 0})
    episodes: list[str] = []
    stopped = False
    t0 = time.monotonic()

    for i, spec in enumerate(specs, 1):
        cell = matrix[(spec.vertical, spec.framework)]
        prefix = f"[{i}/{len(specs)}] {spec.id}"
        try:
            ep = build_and_run(spec, model=args.model, client=guard)
        except BudgetExceeded as exc:
            print(f"  {prefix}: BUDGET STOP — {exc}")
            stopped = True
            break
        except Exception as exc:  # a live API/agent failure — record + continue
            cell["fail"] += 1
            print(f"  {prefix}: FAIL {type(exc).__name__}: {str(exc)[:120]}")
            continue

        if not ep:
            cell["skip"] += 1
            print(f"  {prefix}: skip (no key/framework)")
            continue

        cell["ok"] += 1
        epid = ep.get("episode_id")
        if epid:
            episodes.append(epid)
        # Liveness marker: a real tool fired (recorded path) or tool_calls present.
        if ep.get("tool_calls") or epid:
            cell["live_data"] += 1
        final = str(ep.get("final_content") or "")[:90].replace("\n", " ")
        print(f"  {prefix}: ok  ep={epid or '-'}  {final}")

    _print_matrix(matrix)
    elapsed = time.monotonic() - t0
    print(f"\n{guard.report()}")
    print(f"episodes recorded: {len(episodes)}   wall-clock: {elapsed:.0f}s"
          f"{'   (stopped early on budget)' if stopped else ''}")
    if episodes and recording:
        base = os.environ.get("AGEVAL_API_URL", "http://localhost:8088")
        print(f"→ scored episodes at {base} (e.g. {episodes[0]})")
    return 0


def _print_matrix(matrix: dict) -> None:
    verts = sorted({v for (v, _f) in matrix})
    frames = sorted({f for (_v, f) in matrix})
    print("\n=== vertical × framework coverage (ok / live-data) ===")
    width = max((len(v) for v in verts), default=10) + 2
    header = " " * width + "".join(f"{f:>14}" for f in frames)
    print(header)
    for v in verts:
        row = f"{v:<{width}}"
        for f in frames:
            c = matrix.get((v, f))
            row += f"{(str(c['ok'])+'/'+str(c['live_data'])):>14}" if c else f"{'-':>14}"
        print(row)
    tot_ok = sum(c["ok"] for c in matrix.values())
    tot_live = sum(c["live_data"] for c in matrix.values())
    tot_fail = sum(c["fail"] for c in matrix.values())
    print(f"\ntotals: ok={tot_ok}  live-data={tot_live}  fail={tot_fail}")


if __name__ == "__main__":
    raise SystemExit(main())
