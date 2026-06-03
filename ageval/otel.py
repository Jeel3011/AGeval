"""
ageval/otel.py

OpenTelemetry integration for AGeval.
Maps AGeval episode and step data to OpenTelemetry GenAI semantic conventions.
"""

import logging

log = logging.getLogger(__name__)

_otel_tracer = None

def setup_otel(tracer_provider=None, service_name: str = "ageval-agent"):
    """
    Initialize the OpenTelemetry exporter for AGeval.
    """
    global _otel_tracer
    try:
        from opentelemetry import trace
        if tracer_provider:
            trace.set_tracer_provider(tracer_provider)
        _otel_tracer = trace.get_tracer(service_name)
    except ImportError:
        log.warning("opentelemetry-api is not installed. Run `pip install opentelemetry-api`.")
        _otel_tracer = None

def export_episode(episode: dict, steps: list[dict]):
    """
    Export a full episode and its steps as OpenTelemetry spans.
    Follows GenAI semantic conventions where possible.
    """
    if not _otel_tracer:
        return

    from opentelemetry import trace

    episode_id = episode.get("episode_id", "unknown")
    agent_id = episode.get("agent_id", "unknown")
    task = episode.get("task", "")
    outcome = episode.get("outcome", "unknown")

    # Start a trace for the whole episode
    with _otel_tracer.start_as_current_span(
        name=f"agent.episode.{agent_id}",
        attributes={
            "gen_ai.system": "ageval",
            "gen_ai.agent.id": agent_id,
            "gen_ai.episode.id": episode_id,
            "gen_ai.task": task,
            "gen_ai.outcome": outcome,
        }
    ) as ep_span:
        if outcome == "failure":
            ep_span.set_status(trace.StatusCode.ERROR, "Episode failed")

        for step in steps:
            tool_name = step.get("tool_name", "unknown")
            latency = step.get("latency_ms") or 0  # latency_ms may be present-but-None

            with _otel_tracer.start_as_current_span(
                name=f"agent.tool.{tool_name}",
                attributes={
                    "gen_ai.tool.name": tool_name,
                    "gen_ai.tool.success": step.get("success", False),
                    "gen_ai.tool.reasoning": step.get("reasoning", ""),
                    "gen_ai.tool.latency_ms": latency,
                }
            ) as tool_span:
                if not step.get("success", True):
                    tool_span.set_status(
                        trace.StatusCode.ERROR,
                        step.get("error_message") or "Tool failed"
                    )
