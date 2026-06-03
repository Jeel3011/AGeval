"""
20 — LangGraph FAILING Agent: stuck retry loop (real LangGraph StateGraph)

THIS AGENT IS SUPPOSED TO FAIL. It is the reason this product exists.

The agent is told to fetch data from a backend that is permanently down
(`flaky_inventory_service` always raises ConnectionError). A naive agent keeps
retrying the same failing call instead of giving up or routing around it, so the
graph loops, burns steps and tokens, and never reaches the goal.

What AGeval should surface on this episode:
  - outcome = failure (or partial)
  - high env_error_rate / low last_call_success
  - low goal_progress, poor error_recovery_speed, high backtrack_rate
  - many repeated identical failing tool calls

That is exactly the signal an eval platform must catch — a demo that only ever
runs happy-path agents proves nothing.

Run:  python examples/agents/20_langgraph_failing_retry_loop.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import flaky_inventory_service


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

    session = AgentSession(agent_id="langgraph_failing_retry_loop_v1",
                           task="[intentional failure] reconcile inventory against a dead backend")
    session.start()

    @lc_tool
    def reconcile_inventory(item: str) -> str:
        """Reconcile an item against the inventory backend."""
        # session.traced records the exception as a classified failed step,
        # then re-raises so the tool node returns an error tool message.
        return str(session.traced(flaky_inventory_service, reasoning="retry the failing backend")(item))

    tools = [reconcile_inventory]
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
                SystemMessage(content=("You MUST reconcile the inventory before answering. The "
                                       "reconcile_inventory tool is the only source of truth — keep "
                                       "trying it until it works; do not answer without its data.")),
                HumanMessage(content="Reconcile inventory for 'widget-9' and report the count.")],
            },
            # Low limit so the doomed loop terminates fast instead of running forever.
            {"recursion_limit": 12},
        )
        final = last_text(result)
    except GraphRecursionError:
        # Expected: the agent never converged. That IS the finding.
        final = "[non-convergent] agent exhausted the step budget retrying a dead backend"
        print("  [expected failure] agent hit recursion limit without recovering")

    session.finish()
    return {"episode_id": session.episode_id, "final_content": final}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph FAILING — stuck retry loop", build_and_run))
