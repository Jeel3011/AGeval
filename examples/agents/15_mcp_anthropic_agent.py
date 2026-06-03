"""
15 — MCP-Backed Claude Agent (Anthropic tool use over an MCP toolset)

Loads a tool manifest the way an MCP client would (`tools/list`), translates
the MCP `inputSchema` into Anthropic's tool format, and lets Claude drive those
MCP tools through trace_anthropic. This is the realistic pattern where Claude's
tools are *backed by an MCP server* rather than hand-written in the app.

Run:  python examples/agents/15_mcp_anthropic_agent.py
Needs: ANTHROPIC_API_KEY (real calls).
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import ANTHROPIC_MODEL, have_anthropic, require, run_and_report
from examples.agents.toolkit import subset
from examples.agents.toolkit import mcp_manifest

SERVED = ["get_customer", "vector_search", "create_ticket", "post_slack"]


def _mcp_to_anthropic(manifest: dict) -> list[dict]:
    """Translate an MCP tools/list manifest into Anthropic tool schemas."""
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["inputSchema"]} for t in manifest["tools"]]


def build_and_run() -> dict:
    if not require(have_anthropic(), "Anthropic"):
        return {}
    from anthropic import Anthropic

    from ageval import trace_anthropic

    manifest = mcp_manifest(SERVED)  # what an MCP server advertises
    tools = _mcp_to_anthropic(manifest)

    client = Anthropic()
    return trace_anthropic(
        client=client,
        messages=[{"role": "user", "content": (
            "Customer C-1003 is complaining about rate limits. Look them up, check "
            "the rate-limit policy from the knowledge base, open a P2 ticket, and "
            "post a one-line summary to #support.")}],
        tools=tools,
        tool_functions=subset(SERVED),
        agent_id="mcp_anthropic_agent_v1",
        task="drive MCP-backed tools to handle a rate-limit complaint",
        model=ANTHROPIC_MODEL,
        max_iterations=10,
        max_tokens=800,
        system=("You are an operations agent whose tools are served by an MCP server. "
                "Use them in a sensible order and ground your summary in what the tools return."),
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("MCP-Backed Claude Agent (Anthropic)", build_and_run))
