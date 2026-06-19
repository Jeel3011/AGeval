"""
examples/agents/_common.py

Shared helpers for the example agents: env loading, a banner, and a uniform
"run + report" wrapper so every agent file ends the same way:

    if __name__ == "__main__":
        run_and_report("billing_agent", build_and_run)

Each agent's `build_and_run()` performs a REAL traced episode (real LLM calls
through AGeval's tracers, or a real framework loop) and returns the dict that
the tracers/AgentSession produce (must contain "episode_id").

These files make real model calls. To keep a full sweep cheap, the toolkit's
tools are local (no paid external calls) — the only cost is model tokens, and
the agents default to the cheapest models with low temperature and a small
iteration budget.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Callable

# Make `from examples.agents.toolkit import ...` and `import ageval` both work
# regardless of where the file is run from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for p in (_ROOT,):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
    pass

# Cheap defaults so a full sweep stays inexpensive.
OPENAI_MODEL = os.environ.get("AGEVAL_DEMO_OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.environ.get("AGEVAL_DEMO_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


def banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")


def have_openai() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def have_anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def require(flag: bool, what: str) -> bool:
    if not flag:
        print(f"  [skip] {what} not configured — set the appropriate API key to run live.")
    return flag


def run_and_report(agent_name: str, build_and_run: Callable[[], dict]) -> int:
    """Run one agent's real episode and print what AGeval recorded."""
    banner(agent_name)
    try:
        result = build_and_run()
    except SystemExit:
        raise
    except Exception:
        print(f"  [error] {agent_name} crashed:")
        traceback.print_exc()
        return 1

    if not result:
        print(f"  [skip] {agent_name} did not run (missing key or framework).")
        return 0

    ep = result.get("episode_id")
    final = result.get("final_content")
    if ep:
        print(f"  episode_id = {ep}")
        if os.environ.get("AGEVAL_API_KEY"):
            base = os.environ.get("AGEVAL_API_URL", "https://ageval-api.onrender.com")
            print(f"  → scores will appear at {base} (episode {ep})")
        else:
            print("  (AGEVAL_API_KEY not set — ran live but not recorded to AGeval)")
    if final:
        print(f"  final: {str(final)[:200]}")
    return 0
