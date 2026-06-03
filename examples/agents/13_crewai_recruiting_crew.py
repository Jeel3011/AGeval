"""
13 — CrewAI Recruiting Crew (real CrewAI multi-agent crew)

A Sourcer + Scheduler crew: the sourcer screens candidates against criteria,
the scheduler books interviews and emails the candidate. Demonstrates AGeval
tracing across a CrewAI hand-off where tool use is split between two agents.

Run:  python examples/agents/13_crewai_recruiting_crew.py
Needs: OPENAI_API_KEY, and `pip install crewai crewai-tools`.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import book_calendar, run_python, send_email


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

    session = AgentSession(agent_id="crewai_recruiting_crew_v1",
                           task="screen a candidate and book + confirm an interview")
    session.start()

    @crew_tool("score_candidate")
    def score_candidate(code: str) -> str:
        """Run a tiny scoring snippet (sets `result`) to rank a candidate's fit 0-100."""
        return str(session.traced(run_python, reasoning="compute a fit score")(code))

    @crew_tool("schedule_interview")
    def schedule_interview(title: str, start_iso: str, duration_min: int = 45) -> str:
        """Book an interview on the calendar."""
        return str(session.traced(book_calendar, reasoning="book the interview slot")(title, start_iso, duration_min))

    @crew_tool("email_candidate")
    def email_candidate(to: str, subject: str, body: str) -> str:
        """Email the candidate."""
        return str(session.traced(send_email, reasoning="confirm the interview")(to, subject, body))

    sourcer = Agent(
        role="Technical Sourcer",
        goal="Score a candidate's fit out of 100 using a transparent formula.",
        backstory="You quantify fit; you compute scores, never guess them.",
        tools=[score_candidate], llm=OPENAI_MODEL, verbose=False,
    )
    scheduler = Agent(
        role="Coordinator",
        goal="If fit >= 70, book a 45-min interview and email the candidate.",
        backstory="You schedule efficiently and confirm in writing.",
        tools=[schedule_interview, email_candidate], llm=OPENAI_MODEL, verbose=False,
    )

    score_task = Task(
        description=("Candidate has 6 years experience and 4 relevant skills. Compute fit as "
                     "result = min(100, years*8 + skills*10) using the scoring tool."),
        expected_output="The numeric fit score.", agent=sourcer,
    )
    book_task = Task(
        description=("If fit >= 70, book 'Onsite Interview' for 2026-06-25T16:00:00Z and email "
                     "candidate@dev.example a confirmation. Otherwise send a polite decline."),
        expected_output="Confirmation that the interview was booked and emailed.",
        agent=scheduler, context=[score_task],
    )

    crew = Crew(agents=[sourcer, scheduler], tasks=[score_task, book_task],
                process=Process.sequential, verbose=False)
    output = crew.kickoff()

    session.finish()
    return {"episode_id": session.episode_id, "final_content": str(output)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("CrewAI Recruiting Crew", build_and_run))
