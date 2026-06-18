"""
Run all flagship framework agents (LangGraph StateGraph + ReAct, MCP,
zero-code ageval.auto) against REAL APIs. Each module exposes a `build_and_run`
returning an AGeval episode dict; missing frameworks skip gracefully.

Run:  python -m examples.agents.fleet.flagships.run_flagships
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import examples.agents._common  # noqa: F401,E402  - loads .env
from examples.agents._common import run_and_report  # noqa: E402


def _flagship_modules() -> list[str]:
    import examples.agents.fleet.flagships as pkg
    names = []
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith(("run_", "_")):
            continue
        names.append(f"examples.agents.fleet.flagships.{m.name}")
    return sorted(names)


def main() -> int:
    mods = _flagship_modules()
    print(f"Discovered {len(mods)} flagship agents.\n")
    rc = 0
    for modname in mods:
        mod = importlib.import_module(modname)
        if not hasattr(mod, "build_and_run"):
            continue
        rc |= run_and_report(modname.split(".")[-1], mod.build_and_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
