"""
08 — Coding Agent (Anthropic / Claude tool use)

A software agent that writes a small function to a file, then executes it in
a sandbox to verify it works — the read/write/run loop real coding agents use.

Exercises write_file, read_file, run_python.

Run:  python examples/agents/08_coding_agent_anthropic.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import ANTHROPIC_MODEL, have_anthropic, require, run_and_report
from examples.agents.toolkit import anthropic_schemas, subset

TOOLS = ["write_file", "read_file", "run_python"]


def build_and_run() -> dict:
    if not require(have_anthropic(), "Anthropic"):
        return {}
    from anthropic import Anthropic

    from ageval import trace_anthropic

    client = Anthropic()
    return trace_anthropic(
        client=client,
        messages=[{"role": "user", "content": (
            "Write a Python function `fib(n)` returning the n-th Fibonacci number "
            "to the file solution.py, then run a snippet that imports nothing and "
            "computes result = fib(10) so I can see it equals 55. Verify before "
            "you finish.")}],
        tools=anthropic_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="coding_agent_v1",
        task="write and verify fib(n)",
        model=ANTHROPIC_MODEL,
        max_iterations=10,
        max_tokens=900,
        system=("You are a coding agent. Write code to files, then run it to "
                "verify. The sandbox forbids imports and file I/O inside run_python "
                "— inline the function body in the snippet you execute."),
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("Coding Agent (Anthropic)", build_and_run))
