"""
11 — LangGraph Human-in-the-Loop Approval (real LangGraph + checkpointer)

A refund-approval workflow that pauses for human approval before charging,
using LangGraph's interrupt/checkpoint mechanism. The full run — including the
post-approval payment — is captured as one AGeval episode.

This mirrors a real high-stakes agent (finance/ops) where a human gate sits in
front of an irreversible action.

Run:  python examples/agents/11_langgraph_human_in_loop.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import get_customer, process_payment, send_email


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.tools import tool as lc_tool
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, START, StateGraph

        from examples.agents._lgstate import MessagesState, last_text, make_tool_node
    except ImportError:
        print("  [skip] LangGraph not installed. Run: pip install langgraph langchain-openai")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="langgraph_human_in_loop_v1",
                           task="approve-then-refund with a human gate")
    session.start()

    @lc_tool
    def lookup(customer_id: str) -> str:
        """Look up a customer."""
        return str(session.traced(get_customer, reasoning="verify the account")(customer_id))

    @lc_tool
    def issue_refund(amount: float) -> str:
        """Refund the customer (irreversible — requires prior approval)."""
        return str(session.traced(process_payment, reasoning="execute approved refund")(amount, "USD", "card"))

    @lc_tool
    def notify_customer(to: str, subject: str, body: str) -> str:
        """Email the customer."""
        return str(session.traced(send_email, reasoning="confirm the refund")(to, subject, body))

    tools = [lookup, issue_refund, notify_customer]
    tools_by_name = {t.name: t for t in tools}
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0).bind_tools(tools)

    # Unannotated on purpose — see note in 09; avoids LangGraph re-evaluating a
    # deferred annotation string under `from __future__ import annotations`.
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
    # Interrupt before any tool execution so a human can approve the refund.
    graph = g.compile(checkpointer=MemorySaver(), interrupt_before=["tools"])

    cfg = {"configurable": {"thread_id": "refund-001"}}
    seed = {"messages": [
        SystemMessage(content="You are a refunds agent. Look up the customer, then issue the "
                              "approved refund and email confirmation to billing@acme.example."),
        HumanMessage(content="Refund $42.00 to customer C-1001 for the outage. Then confirm by email."),
    ]}

    # The graph interrupts before EVERY tool batch. A human operator approves at
    # each gate; we drain interrupts until the graph runs to completion. (Each
    # `graph.get_state` with a `next` node means we're paused at a gate.)
    result = graph.invoke(seed, cfg)
    gates = 0
    while graph.get_state(cfg).next and gates < 12:
        gates += 1
        print(f"  [human-in-the-loop] gate {gates}: operator approves — resuming graph")
        result = graph.invoke(None, cfg)

    session.finish()
    return {"episode_id": session.episode_id, "final_content": last_text(result)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph Human-in-the-Loop", build_and_run))
