"""
12 — CrewAI Marketing Crew (real CrewAI multi-agent crew)

A two-agent CrewAI crew (Researcher + Copywriter) that researches the product
KB and drafts launch copy, then posts it to Slack. Each CrewAI tool call is
recorded to AGeval via an AgentSession, so the whole crew run is one scored
episode — showing AGeval works for multi-agent orchestration, not just single
loops.

Run:  python examples/agents/12_crewai_marketing_crew.py
Needs: OPENAI_API_KEY, and `pip install crewai crewai-tools`.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import post_slack, vector_search


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from crewai import Agent, Crew, Process, Task
        from crewai.tools import tool as crew_tool
    except ImportError:
        print("  [skip] CrewAI not installed. Run: pip install crewai crewai-tools")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="crewai_marketing_crew_v1",
                           task="research the product and draft + post launch copy")
    session.start()

    @crew_tool("search_kb")
    def search_kb(query: str) -> str:
        """Search the product knowledge base for facts to ground the copy."""
        return str(session.traced(vector_search, reasoning="gather grounded facts")(query))

    @crew_tool("publish_slack")
    def publish_slack(channel: str, text: str) -> str:
        """Publish the final copy to a Slack channel."""
        return str(session.traced(post_slack, reasoning="ship the announcement")(channel, text))

    researcher = Agent(
        role="Product Researcher",
        goal="Find accurate, citable facts about the product from the KB.",
        backstory="You never invent facts; you ground every claim in the KB.",
        tools=[search_kb], llm=OPENAI_MODEL, verbose=False,
    )
    writer = Agent(
        role="Launch Copywriter",
        goal="Write a crisp 3-sentence launch announcement and post it to #launches.",
        backstory="You turn researched facts into punchy, honest copy.",
        tools=[publish_slack], llm=OPENAI_MODEL, verbose=False,
    )

    research_task = Task(
        description=("Research the enterprise SLA and data-residency facts from the KB."),
        expected_output="A short bullet list of grounded facts with their source titles.",
        agent=researcher,
    )
    write_task = Task(
        description=("Using the researched facts, write a 3-sentence launch note and "
                     "post it to the #launches Slack channel."),
        expected_output="The posted announcement text.",
        agent=writer, context=[research_task],
    )

    crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task],
                process=Process.sequential, verbose=False)
    output = crew.kickoff()

    session.finish()
    return {"episode_id": session.episode_id, "final_content": str(output)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("CrewAI Marketing Crew", build_and_run))
