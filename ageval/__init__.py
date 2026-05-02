"""
ageval — Episodic evaluation framework for LLM agents.

Works with ANY agent framework:

  LangGraph / LangChain:
      from ageval import trace_agent
      result = trace_agent(agent=your_graph, input=messages, agent_id="v1")

  OpenAI function calling:
      from ageval import trace_openai
      result = trace_openai(client, messages, tools, tool_functions,
                            agent_id="v1", task="do X")

  Any framework (CrewAI, AutoGen, custom):
      from ageval import AgentSession
      with AgentSession(agent_id="v1", task="do X") as session:
          result = my_tool(args)
          session.record_step(tool_name="my_tool", tool_output=result, success=True)

  Simple callable:
      from ageval import trace_callable
      result = trace_callable(my_fn, args=(x,), agent_id="v1", task="do X")

Required env vars (user-side):
    AGEVAL_API_KEY   — your ageval API key (the only thing you need)

Optional:
    AGEVAL_API_URL   — override the API base (default: ageval-production.up.railway.app)

Fallback:
    If AGEVAL_API_KEY is not set, all trace functions fall back to plain
    execution — no crashes, no overhead.
"""

# Framework-agnostic (works with ANY agent)
from ageval.session import AgentSession, trace_callable, classify_error

# Custom metrics
from ageval.metrics import register_metric, list_metrics, score_with_custom_metrics

# LangGraph / LangChain (optional — only works if langchain is installed)
from ageval.tracer import trace_agent, recall_episodes, compare_episodes

# OpenAI function calling (optional — only works if openai is installed)
try:
    from ageval.openai_tracer import trace_openai
except ImportError:
    trace_openai = None  # type: ignore[assignment]

__all__ = [
    # Universal
    "AgentSession",
    "trace_callable",
    "classify_error",
    # Metrics
    "register_metric",
    "list_metrics",
    "score_with_custom_metrics",
    # LangGraph
    "trace_agent",
    "recall_episodes",
    "compare_episodes",
    # OpenAI
    "trace_openai",
]

__version__ = "0.3.0"
