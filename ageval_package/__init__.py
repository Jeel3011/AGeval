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

Required env vars (user-side):
    AGEVAL_API_KEY   — your ageval API key (the only thing you need)

Optional:
    AGEVAL_API_URL   — override the API base (default: ageval-production.up.railway.app)

Fallback:
    If AGEVAL_API_KEY is not set, trace_agent() falls back to a plain
    agent.invoke() — no crashes, no overhead.
"""

from ageval_package.tracer import trace_agent, recall_episodes, compare_episodes

__all__    = ["trace_agent", "recall_episodes", "compare_episodes"]
__version__ = "0.2.0"
