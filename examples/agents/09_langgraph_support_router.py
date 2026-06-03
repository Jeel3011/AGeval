"""
09 — LangGraph Support Router (real LangGraph StateGraph)

A genuine LangGraph agent: a StateGraph with an LLM node bound to tools and a
ToolNode, looping until the model stops calling tools. Every tool execution is
recorded to AGeval through an AgentSession, so the graph run becomes a scored
episode.

This is exactly how a production LangGraph app integrates AGeval: wrap your
tools with `session.traced(...)` (or record_step inside the node) and open one
AgentSession per graph invocation.

Run:  python examples/agents/09_langgraph_support_router.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import (
    create_ticket,
    get_customer,
    post_slack,
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

    session = AgentSession(agent_id="langgraph_support_router_v1",
                           task="route a support request through a LangGraph graph")
    session.start()

    # Wrap the real toolkit functions so each invocation is a recorded step.
    @lc_tool
    def lookup_customer(customer_id: str) -> str:
        """Look up a customer by id."""
        return str(session.traced(get_customer, reasoning="identify the customer")(customer_id))

    @lc_tool
    def search_kb(query: str) -> str:
        """Search the knowledge base."""
        return str(session.traced(vector_search, reasoning="find relevant policy")(query))

    @lc_tool
    def open_ticket(subject: str, priority: str = "P3") -> str:
        """Open a support ticket."""
        return str(session.traced(create_ticket, reasoning="escalate unresolved issue")(subject, priority))

    @lc_tool
    def notify(channel: str, text: str) -> str:
        """Post a Slack notification."""
        return str(session.traced(post_slack, reasoning="notify the on-call channel")(channel, text))

    tools = [lookup_customer, search_kb, open_ticket, notify]
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0).bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    # Note: these node/branch fns are intentionally unannotated. With
    # `from __future__ import annotations` LangGraph would otherwise try to
    # resolve the annotation string against this function's module globals
    # (where the locally-imported MessagesState isn't visible) and fail.
    def agent_node(state):
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", make_tool_node(tools_by_name))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    graph = g.compile()

    result = graph.invoke({"messages": [
        SystemMessage(content=("You are a support router. Identify the customer, search the KB, "
                               "and if the issue is unresolved open a P2 ticket and notify #support.")),
        HumanMessage(content=("Customer C-1003 reports they are hitting rate limits constantly. "
                              "Look them up, check the rate-limit policy, and if their plan can't "
                              "support the load, open a ticket and notify #support.")),
    ]})

    session.finish()
    return {"episode_id": session.episode_id, "final_content": last_text(result)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph Support Router", build_and_run))
