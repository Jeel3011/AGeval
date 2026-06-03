"""
14 — MCP Server + Client Agent (real Model Context Protocol)

Spins up a real in-process MCP server (using the official `mcp` SDK) that
exposes a subset of the toolkit as MCP tools, connects an MCP client to it over
an in-memory stream, lists the tools, and calls them — recording each
`tools/call` to AGeval as an episode step.

This is the canonical "agent talks to an MCP server" loop, proving AGeval
traces tools served over MCP exactly like native tools.

Run:  python examples/agents/14_mcp_server_agent.py
Needs: `pip install mcp`.  (LLM-free — exercises the MCP transport itself.)
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import asyncio

from examples.agents._common import run_and_report
from examples.agents.toolkit import TOOL_FUNCTIONS, mcp_manifest


def build_and_run() -> dict:
    try:
        import mcp.types as types
        from mcp.server.lowlevel import Server
        from mcp.shared.memory import create_connected_server_and_client_session
    except ImportError:
        print("  [skip] MCP SDK not installed. Run: pip install mcp")
        return {}

    from ageval import AgentSession

    served = ["get_customer", "vector_search", "create_ticket"]
    manifest = mcp_manifest(served)

    # ---- Build a real MCP server exposing toolkit functions as MCP tools ----
    server = Server("ageval-demo-tools")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"],
                           inputSchema=t["inputSchema"]) for t in manifest["tools"]]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        fn = TOOL_FUNCTIONS[name]
        return [types.TextContent(type="text", text=str(fn(**arguments)))]

    async def drive() -> dict:
        session = AgentSession(agent_id="mcp_server_agent_v1",
                               task="call tools served over MCP")
        session.start()
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
            listed = await client.list_tools()
            tool_names = [t.name for t in listed.tools]

            # A small deterministic plan over the MCP tools.
            plan = [
                ("get_customer", {"customer_id": "C-1003"}, "identify the account"),
                ("vector_search", {"query": "rate limits per plan", "k": 2}, "find the policy"),
                ("create_ticket", {"subject": "Initech rate-limit escalation", "priority": "P2"},
                 "escalate the issue"),
            ]
            final = None
            for name, args, why in plan:
                import time as _t
                t0 = _t.perf_counter()
                res = await client.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                session.record_step(
                    tool_name=name, tool_input=args, tool_output=text, success=True,
                    reasoning=why, latency_ms=int((_t.perf_counter() - t0) * 1000),
                )
                final = text
        session.finish()
        return {"episode_id": session.episode_id,
                "final_content": f"served {tool_names}; last result: {final}"}

    return asyncio.run(drive())


if __name__ == "__main__":
    raise SystemExit(run_and_report("MCP Server + Client Agent", build_and_run))
