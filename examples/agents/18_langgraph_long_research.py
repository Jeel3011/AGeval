"""
18 — LangGraph Long-Running Research Agent (real LangGraph StateGraph)

A genuinely long-running agent: it works a multi-part research brief that forces
~15-25 tool calls (one customer + product + KB lookup per line item, plus
arithmetic), looping through the graph many times. This stresses AGeval on
*step volume* and *latency aggregation* over a long episode — the regime where
real agents drift, repeat work, or stall.

We bump the graph's recursion_limit so LangGraph allows the deep loop, and the
AgentSession records every one of the (many) steps.

Run:  python examples/agents/18_langgraph_long_research.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import (
    calculate,
    get_customer,
    get_product,
    vector_search,
)


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

    session = AgentSession(agent_id="langgraph_long_research_v1",
                           task="multi-part research brief (long-running, many steps)")
    session.start()

    @lc_tool
    def customer(customer_id: str) -> str:
        """Look up a customer by id."""
        return str(session.traced(get_customer, reasoning="pull the account record")(customer_id))

    @lc_tool
    def product(sku: str) -> str:
        """Look up a product by SKU."""
        return str(session.traced(get_product, reasoning="pull the product record")(sku))

    @lc_tool
    def kb(query: str) -> str:
        """Search the knowledge base."""
        return str(session.traced(vector_search, reasoning="gather policy evidence")(query))

    @lc_tool
    def calc(expression: str) -> str:
        """Evaluate arithmetic."""
        return str(session.traced(calculate, reasoning="compute a figure")(expression))

    tools = [customer, product, kb, calc]
    tools_by_name = {t.name: t for t in tools}
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0).bind_tools(tools)

    def agent_node(state):
        return {"messages": [llm.invoke(state["messages"])]}

    def route(state):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", make_tool_node(tools_by_name))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    graph = g.compile()

    brief = (
        "Prepare an account brief. Work through these ONE TOOL CALL AT A TIME, do "
        "not batch: (1) look up customers C-1001, C-1002 and C-1003; (2) for each, "
        "search the KB for the policy relevant to their plan (enterprise SLA, rate "
        "limits, refund policy respectively); (3) look up products SKU-RED-TEE, "
        "SKU-BLU-MUG and SKU-GRN-CAP; (4) using the calculator, compute each "
        "customer's annual revenue (mrr*12) separately, then the grand total. "
        "Finally summarise everything."
    )
    result = graph.invoke(
        {"messages": [
            SystemMessage(content="You are a meticulous research agent. Make exactly one tool "
                                  "call per step and reason briefly before each."),
            HumanMessage(content=brief),
        ]},
        {"recursion_limit": 60},
    )

    session.finish()
    return {"episode_id": session.episode_id, "final_content": last_text(result)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph Long-Running Research", build_and_run))
