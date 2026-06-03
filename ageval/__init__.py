"""
ageval — Episodic evaluation framework for LLM agents.

ZERO code changes (recommended) — instrument an existing agent with ONE line:

      import ageval.auto   # patches OpenAI/Anthropic + installs a global
                           # LangChain/LangGraph callback at import time.
                           # CrewAI/AutoGen are covered transitively.

Or integrate explicitly with any agent framework:

  LangGraph / LangChain:
      from ageval import trace_agent
      result = trace_agent(agent=your_graph, input=messages, agent_id="v1")

  OpenAI function calling:
      from ageval import trace_openai
      result = trace_openai(client, messages, tools, tool_functions,
                            agent_id="v1", task="do X")

  Anthropic (Claude) tool use:
      from ageval import trace_anthropic
      result = trace_anthropic(client, messages, tools, tool_functions,
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

# Custom metrics + built-in metric catalogue
from ageval.metrics import (
    register_metric,
    list_metrics,
    get_metric,
    unregister_metric,
    score_with_custom_metrics,
    # built-in reliability
    agent_error_rate,
    env_error_rate,
    fatal_error_rate,
    first_call_success,
    last_call_success,
    # built-in efficiency
    step_economy,
    p95_step_latency,
    retry_overhead,
    # built-in agentic
    tool_call_precision,
    goal_progress,
    reasoning_depth,
    # built-in backtracking / cost
    backtrack_rate,
    token_economy,
    reasoning_action_alignment,
    # built-in observability
    tool_diversity,
    multi_tool_usage,
    output_richness,
    latency_budget,
    error_recovery_speed,
    # deep evaluation (v2)
    recovery_success_rate,
    failure_clustering,
    tool_selection_entropy,
    progress_monotonicity,
    cost_per_success,
    latency_consistency,
    error_concentration,
)

# LangGraph / LangChain (optional — only works if langchain is installed)
from ageval.tracer import trace_agent, recall_episodes, compare_episodes

# OpenAI function calling (optional — only works if openai is installed)
try:
    from ageval.openai_tracer import trace_openai
except ImportError:
    trace_openai = None  # type: ignore[assignment]

# Anthropic (Claude) tool use. The tracer only imports the AGeval session, not
# the anthropic SDK itself (the caller passes the client), so this import is
# always safe — keep the try/except purely defensive.
try:
    from ageval.anthropic_tracer import trace_anthropic
except ImportError:  # pragma: no cover - defensive
    trace_anthropic = None  # type: ignore[assignment]

__all__ = [
    # Universal
    "AgentSession",
    "trace_callable",
    "classify_error",
    # Metric registry
    "register_metric",
    "unregister_metric",
    "list_metrics",
    "get_metric",
    "score_with_custom_metrics",
    # Built-in reliability metrics
    "agent_error_rate",
    "env_error_rate",
    "fatal_error_rate",
    "first_call_success",
    "last_call_success",
    # Built-in efficiency metrics
    "step_economy",
    "p95_step_latency",
    "retry_overhead",
    # Built-in agentic metrics
    "tool_call_precision",
    "goal_progress",
    "reasoning_depth",
    # Built-in backtracking / cost metrics
    "backtrack_rate",
    "token_economy",
    "reasoning_action_alignment",
    # Built-in observability metrics
    "tool_diversity",
    "multi_tool_usage",
    "output_richness",
    "latency_budget",
    "error_recovery_speed",
    # Deep evaluation metrics (v2)
    "recovery_success_rate",
    "failure_clustering",
    "tool_selection_entropy",
    "progress_monotonicity",
    "cost_per_success",
    "latency_consistency",
    "error_concentration",
    # LangGraph
    "trace_agent",
    "recall_episodes",
    "compare_episodes",
    # OpenAI
    "trace_openai",
    # Anthropic
    "trace_anthropic",
]

__version__ = "0.3.0"
