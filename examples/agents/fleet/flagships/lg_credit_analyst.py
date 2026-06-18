"""
Flagship — LangGraph credit analyst on REAL APIs.

A genuine LangGraph StateGraph (LLM node bound to tools + a tool node, looping
until the model stops). Unlike the toolkit-based example 09, every tool here
hits a *live* API: SEC EDGAR for 10-K facts and the World Bank for macro
context. Each tool call is recorded to AGeval through an AgentSession, so the
graph run becomes a real scored episode.

Run:  python -m examples.agents.fleet.flagships.lg_credit_analyst
Needs: OPENAI_API_KEY (+ AGEVAL_API_KEY to record), pip install langgraph langchain-openai
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.real_tools import sec_company_facts, world_bank_indicator


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

    session = AgentSession(agent_id="flagship_lg_credit_analyst_v1",
                           task="assess a public company's credit using live SEC + World Bank data")
    session.start()

    @lc_tool
    def company_facts(cik: str) -> str:
        """Latest SEC EDGAR 10-K assets/liabilities/revenue for a 10-digit CIK."""
        return str(session.traced(sec_company_facts, reasoning="pull the latest 10-K facts")(cik))

    @lc_tool
    def macro_indicator(country: str = "US", indicator: str = "NY.GDP.MKTP.CD") -> str:
        """Latest World Bank indicator value (default GDP, current US$)."""
        return str(session.traced(world_bank_indicator, reasoning="add macro context")(country, indicator))

    tools = [company_facts, macro_indicator]
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
        SystemMessage(content="You are a credit analyst. Use the tools for every fact; never invent figures. "
                              "Pull the company's 10-K assets and liabilities, compute the leverage ratio, "
                              "add one line of macro context, and give a one-paragraph credit view."),
        HumanMessage(content="Assess Apple Inc. (CIK 320193). Add US GDP as macro context."),
    ]})

    final = last_text(result)
    session.finish()
    return {"episode_id": session.episode_id, "final_content": final}


if __name__ == "__main__":
    raise SystemExit(run_and_report("Flagship — LangGraph Credit Analyst (real SEC + World Bank)", build_and_run))
