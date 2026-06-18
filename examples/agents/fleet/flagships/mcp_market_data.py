"""
Flagship — real MCP server/client over LIVE market-data tools.

Spins up a real in-process MCP server (official `mcp` SDK) that serves a subset
of real_tools as MCP tools, connects a client over an in-memory stream, lists
the tools and calls them — each `tools/call` hits a *live* API (CoinGecko FX,
World Bank) and is recorded to AGeval as an episode step. Proves AGeval traces
tools served over MCP exactly like native tools, on real traffic.

Run:  python -m examples.agents.fleet.flagships.mcp_market_data
Needs: pip install mcp   (LLM-free — exercises the MCP transport + live APIs.)
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))

import asyncio

from examples.agents._common import run_and_report
from examples.agents.real_tools import TOOL_FUNCTIONS, mcp_manifest


def build_and_run() -> dict:
    try:
        import mcp.types as types
        from mcp.server.lowlevel import Server
        from mcp.shared.memory import create_connected_server_and_client_session
    except ImportError:
        print("  [skip] MCP SDK not installed. Run: pip install mcp")
        return {}

    from ageval import AgentSession

    served = ["crypto_price", "fx_rate", "world_bank_indicator"]
    manifest = mcp_manifest(served)

    server = Server("ageval-real-market-data")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"],
                           inputSchema=t["inputSchema"]) for t in manifest["tools"]]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        fn = TOOL_FUNCTIONS[name]
        return [types.TextContent(type="text", text=str(fn(**arguments)))]

    async def drive() -> dict:
        session = AgentSession(agent_id="flagship_mcp_market_data_v1",
                               task="call live market-data tools served over MCP")
        session.start()
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
            listed = await client.list_tools()
            tool_names = [t.name for t in listed.tools]

            plan = [
                ("crypto_price", {"ids": "bitcoin,ethereum", "vs": "usd"}, "pull live crypto spot"),
                ("fx_rate", {"base": "USD", "symbols": "EUR,GBP"}, "pull live FX"),
                ("world_bank_indicator", {"country": "US"}, "pull US GDP for context"),
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
                "final_content": f"served {tool_names}; last live result: {final}"}

    return asyncio.run(drive())


if __name__ == "__main__":
    raise SystemExit(run_and_report("Flagship — MCP Server/Client over live market data", build_and_run))
