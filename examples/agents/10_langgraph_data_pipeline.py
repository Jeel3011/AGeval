"""
10 — LangGraph Data Pipeline (real LangGraph, ReAct prebuilt)

Uses LangGraph's prebuilt `create_react_agent` — the most common way teams
ship a LangGraph agent — to run an analytics task over the customer DB, with
each tool call recorded to AGeval.

Run:  python examples/agents/10_langgraph_data_pipeline.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import calculate, currency_convert, sql_query


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from langchain_core.tools import tool as lc_tool
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        print("  [skip] LangGraph not installed. Run: pip install langgraph langchain-openai")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="langgraph_data_pipeline_v1",
                           task="compute revenue analytics via a ReAct graph")
    session.start()

    @lc_tool
    def run_sql(query: str) -> str:
        """Run a read-only SQL SELECT."""
        return str(session.traced(sql_query, reasoning="pull rows from the warehouse")(query))

    @lc_tool
    def calc(expression: str) -> str:
        """Evaluate arithmetic."""
        return str(session.traced(calculate, reasoning="aggregate the numbers")(expression))

    @lc_tool
    def fx(amount: float, from_ccy: str, to_ccy: str) -> str:
        """Convert currency."""
        return str(session.traced(currency_convert, reasoning="normalise currency")(amount, from_ccy, to_ccy))

    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
    agent = create_react_agent(llm, [run_sql, calc, fx])

    result = agent.invoke({"messages": [
        ("system", "You are a data pipeline agent. Use run_sql to fetch, calc for every "
                   "arithmetic step, and fx for conversions. Never do mental math."),
        ("user", "Rank customers by MRR, take the top one, and report its annual revenue "
                 "(MRR*12) in both USD and GBP."),
    ]})

    session.finish()
    final = result["messages"][-1]
    return {"episode_id": session.episode_id,
            "final_content": getattr(final, "content", str(final))}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph Data Pipeline", build_and_run))
