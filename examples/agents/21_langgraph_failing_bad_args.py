"""
21 — LangGraph FAILING Agent: wrong tool arguments (real LangGraph StateGraph)

THIS AGENT IS SUPPOSED TO FAIL — in a different way than #20.

Here the backend is healthy, but the agent is mis-prompted into calling tools
with arguments that don't exist: it's told to order SKUs and look up customer
ids that are not in the catalogue/CRM. Every call raises a `KeyError`/`ValueError`
(classified by AGeval as an *agent_error*, not an env_error). A good agent would
notice and correct course; a broken one keeps making the same category of
mistake.

What AGeval should surface:
  - outcome = failure / partial
  - high agent_error_rate (NOT env_error_rate — this distinguishes a buggy agent
    from a flaky environment, a core reason this product exists)
  - low tool_call_precision, low goal_progress

Run:  python examples/agents/21_langgraph_failing_bad_args.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import create_order, get_customer


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.tools import tool as lc_tool
        from langchain_openai import ChatOpenAI
        from langgraph.errors import GraphRecursionError
        from langgraph.graph import END, START, StateGraph

        from examples.agents._lgstate import MessagesState, last_text, make_tool_node
    except ImportError:
        print("  [skip] LangGraph not installed. Run: pip install langgraph langchain-openai")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="langgraph_failing_bad_args_v1",
                           task="[intentional failure] act on non-existent SKUs/customers")
    session.start()

    @lc_tool
    def order(sku: str, quantity: int) -> str:
        """Place an order for a SKU."""
        return str(session.traced(create_order, reasoning="order the requested SKU")(sku, quantity))

    @lc_tool
    def customer(customer_id: str) -> str:
        """Look up a customer by id."""
        return str(session.traced(get_customer, reasoning="look up the customer")(customer_id))

    tools = [order, customer]
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

    final = ""
    try:
        result = graph.invoke(
            {"messages": [
                SystemMessage(content=("You are an ordering agent. The catalogue uses ids like "
                                       "SKU-WIDGET-42 and customers like CUST-999. Use exactly the "
                                       "ids the user gives you; do not substitute.")),
                HumanMessage(content=("Look up customer CUST-999 and order 3 units of SKU-WIDGET-42 "
                                      "for them. Use those exact ids."))],
            },
            {"recursion_limit": 12},
        )
        final = last_text(result)
    except GraphRecursionError:
        final = "[non-convergent] agent kept calling tools with invalid ids"
        print("  [expected failure] agent never recovered from bad arguments")

    session.finish()
    return {"episode_id": session.episode_id, "final_content": final}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph FAILING — bad tool args", build_and_run))
