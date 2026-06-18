"""
Flagship — LangGraph prebuilt ReAct agent on REAL APIs (pharmacovigilance).

Uses langgraph's `create_react_agent` (the prebuilt ReAct loop) with tools that
hit live openFDA enforcement + ClinicalTrials.gov. Each tool call is recorded to
AGeval via an AgentSession, so the ReAct run is a real scored episode.

Run:  python -m examples.agents.fleet.flagships.lg_react_pharmacovigilance
Needs: OPENAI_API_KEY (+ AGEVAL_API_KEY to record), pip install langgraph langchain-openai
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.real_tools import clinical_trials, openfda_enforcement


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

    session = AgentSession(agent_id="flagship_lg_react_pharmacovigilance_v1",
                           task="scan live FDA recalls + trials for a drug-safety brief")
    session.start()

    @lc_tool
    def fda_recalls(search: str = "status:Ongoing", limit: int = 3) -> str:
        """Recent FDA drug enforcement (recall) reports."""
        return str(session.traced(openfda_enforcement, reasoning="check active recalls")(search, limit))

    @lc_tool
    def trials(condition: str, limit: int = 3) -> str:
        """Recent ClinicalTrials.gov studies for a condition."""
        return str(session.traced(clinical_trials, reasoning="map the trial landscape")(condition, limit))

    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0)
    agent = create_react_agent(llm, [fda_recalls, trials])

    result = agent.invoke({"messages": [
        ("system", "You are a pharmacovigilance analyst. Use the tools for every fact. "
                   "Summarise current ongoing FDA drug recalls and the trial landscape for diabetes."),
        ("user", "Give me today's drug-safety brief: any ongoing recalls, plus recent diabetes trials."),
    ]})

    msgs = result.get("messages", [])
    final = getattr(msgs[-1], "content", str(msgs[-1])) if msgs else ""
    session.finish()
    return {"episode_id": session.episode_id, "final_content": final}


if __name__ == "__main__":
    raise SystemExit(run_and_report("Flagship — LangGraph ReAct Pharmacovigilance (real openFDA + trials)", build_and_run))
