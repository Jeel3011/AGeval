"""
examples/agents/run_all.py

Run the whole fleet of realistic example agents and summarise what AGeval
recorded. This is the script to point at when proving "AGeval evaluates real,
many-tool agents across real frameworks", not toys.

It will:
  - discover every NN_*.py agent module in this directory,
  - run each one's build_and_run() (real LLM calls where a key is present;
    framework agents print an install hint if their framework is missing),
  - enforce a single shared $0.50 Anthropic budget across ALL Anthropic agents
    via BudgetGuard (so testing the Claude paths can never overspend), and
  - print a table of episode ids + the total Anthropic spend.

Usage:
    python examples/agents/run_all.py                 # everything
    python examples/agents/run_all.py --only 01 05 14 # specific agents
    python examples/agents/run_all.py --no-anthropic  # skip Claude agents
    python examples/agents/run_all.py --cap 0.25      # tighter Anthropic cap

Env:
    OPENAI_API_KEY     — runs the OpenAI + LangGraph/CrewAI/AutoGen agents live
    ANTHROPIC_API_KEY  — runs the Claude agents live (capped by BudgetGuard)
    AGEVAL_API_KEY     — records every episode to AGeval for scoring
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from examples.agents._common import banner, have_anthropic  # noqa: E402


def _install_anthropic_budget(cap: float):
    """Monkeypatch anthropic.Anthropic so every agent's `Anthropic()` is wrapped
    in a single shared BudgetGuard. Returns the guard (or None if unavailable)."""
    if not have_anthropic():
        return None
    try:
        import anthropic
    except ImportError:
        return None
    from examples.agents.budget_guard import BudgetGuard

    real_cls = anthropic.Anthropic
    guard_holder: dict = {}

    def factory(*args, **kwargs):
        client = real_cls(*args, **kwargs)
        if "guard" not in guard_holder:
            guard_holder["guard"] = BudgetGuard(client, usd_cap=cap)
        else:
            # Re-point the shared guard at the newest client instance.
            guard_holder["guard"]._client = client
            guard_holder["guard"].messages._real = client.messages
        return guard_holder["guard"]

    anthropic.Anthropic = factory  # type: ignore[assignment]
    guard_holder["restore"] = real_cls
    return guard_holder


def _discover() -> list[tuple[str, str]]:
    files = sorted(glob.glob(os.path.join(_HERE, "[0-9][0-9]_*.py")))
    return [(re.match(r"(\d+)", os.path.basename(f)).group(1), f) for f in files]


def _load(path: str):
    spec = importlib.util.spec_from_file_location(
        "ageval_agent_" + os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="numeric prefixes to run, e.g. 01 05 14")
    ap.add_argument("--no-anthropic", action="store_true")
    ap.add_argument("--cap", type=float, default=0.50, help="Anthropic USD budget cap")
    args = ap.parse_args()

    agents = _discover()
    if args.only:
        wanted = set(args.only)
        agents = [(n, p) for n, p in agents if n in wanted]

    guard_holder = None if args.no_anthropic else _install_anthropic_budget(args.cap)
    if args.no_anthropic:
        os.environ.pop("ANTHROPIC_API_KEY", None)

    banner(f"AGeval agent fleet — {len(agents)} agents")
    print(f"  OPENAI_API_KEY: {'set' if os.environ.get('OPENAI_API_KEY') else 'MISSING'}")
    print(f"  ANTHROPIC_API_KEY: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'missing'}"
          f"  (cap ${args.cap:.2f})")
    print(f"  AGEVAL_API_KEY: {'set (recording)' if os.environ.get('AGEVAL_API_KEY') else 'not set'}")

    results = []
    for num, path in agents:
        mod = _load(path)
        if not hasattr(mod, "build_and_run"):
            continue
        title = os.path.basename(path)[3:-3].replace("_", " ")
        try:
            res = mod.build_and_run() or {}
        except Exception as exc:
            # BudgetExceeded or any per-agent failure shouldn't kill the sweep.
            print(f"  [{num}] {title}: stopped — {type(exc).__name__}: {exc}")
            res = {}
        ep = res.get("episode_id")
        print(f"  [{num}] {title}: {'episode ' + ep if ep else 'skipped/no-record'}")
        results.append((num, title, ep))

    banner("FLEET SUMMARY")
    ran = [r for r in results if r[2]]
    print(f"  {len(ran)}/{len(results)} agents produced an episode")
    for num, title, ep in results:
        print(f"    [{num}] {title:38s} {ep or '—'}")

    if guard_holder and "guard" in guard_holder:
        print("\n  " + guard_holder["guard"].report())
        import anthropic
        anthropic.Anthropic = guard_holder["restore"]  # type: ignore[assignment]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
