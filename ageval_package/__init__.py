"""
ageval — Episodic evaluation framework for LangGraph agents.

Usage:
    from ageval import trace_agent

    result = trace_agent(
        agent    = your_compiled_graph,
        input    = {"messages": ["plan a trip to Paris"]},
        agent_id = "trip_planner_v1",
        task     = "plan a trip to Paris",
    )

Required env vars:
    AGEVAL_SUPABASE_URL         — AGeval project URL
    AGEVAL_SUPABASE_SERVICE_KEY — service role key
    LANGSMITH_API_KEY           — for trace fetching
    LANGSMITH_PROJECT           — LangSmith project name
"""

from ageval_package.tracer import trace_agent

__all__ = ["trace_agent"]
__version__ = "0.1.0"
