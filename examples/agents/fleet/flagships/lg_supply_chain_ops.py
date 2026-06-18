"""
Flagship — LangGraph supply-chain ops on REAL APIs (multi-tool + side effect).

A LangGraph StateGraph that fans across several live tools (USGS earthquakes,
CityBikes live capacity, geocoding) and, when --live side effects are enabled,
posts a short summary to a real outbound webhook. Each tool call is a recorded
AGeval step.

Run:  python -m examples.agents.fleet.flagships.lg_supply_chain_ops
Needs: OPENAI_API_KEY (+ AGEVAL_API_KEY to record), pip install langgraph langchain-openai
       Set AGEVAL_LIVE_SIDE_EFFECTS=1 and pass a webhook to enable the real POST.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.real_tools import citybikes_network, geocode, recent_earthquakes


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.tools import tool as lc_tool
        from langchain_openai import ChatOpenAI
        from langgraph.graph import END, START, StateGraph

        from examples.agents._lgstate import MessagesState, last_text, make_tool_node
    except ImportError:
        print("  [skip] LangGraph not installed. Run: pip install langgraph langchain-openai")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="flagship_lg_supply_chain_ops_v1",
                           task="assess live supply-chain disruption risk via multiple real APIs")
    session.start()

    @lc_tool
    def quakes(min_magnitude: float = 4.5) -> str:
        """Significant earthquakes in the past day (supplier-region risk)."""
        return str(session.traced(recent_earthquakes, reasoning="flag at-risk supplier regions")(min_magnitude))

    @lc_tool
    def hub_capacity(network: str = "citi-bike-nyc") -> str:
        """Live last-mile micro-mobility capacity for a network."""
        return str(session.traced(citybikes_network, reasoning="check last-mile capacity")(network))

    @lc_tool
    def locate(query: str) -> str:
        """Geocode a facility/port name to lat/lon."""
        return str(session.traced(geocode, reasoning="locate the facility")(query))

    tools = [quakes, hub_capacity, locate]
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0).bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def call_model(state):
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", make_tool_node(tools_by_name))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    app = graph.compile()

    result = app.invoke({"messages": [
        SystemMessage(content="You are a supply-chain operations planner. Use the tools for every fact. "
                              "Check for recent significant earthquakes, the live last-mile capacity of "
                              "citi-bike-nyc, and locate the Port of Rotterdam. Then give a 2-sentence "
                              "disruption-risk readout."),
        HumanMessage(content="Give me today's disruption-risk readout."),
    ]})

    final = last_text(result)
    session.finish()
    return {"episode_id": session.episode_id, "final_content": final}


if __name__ == "__main__":
    raise SystemExit(run_and_report("Flagship — LangGraph Supply-Chain Ops (real USGS + CityBikes + geocode)", build_and_run))
