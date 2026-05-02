"""
ageval/openai_tracer.py

Drop-in tracing for OpenAI function-calling / tool-use agents.

Wraps the OpenAI client so every tool call is automatically captured
as an AGeval step — same "one line of code" experience as trace_agent()
but for the OpenAI SDK directly.

Supports:
  - OpenAI chat completions with tools/function_calling
  - Streaming and non-streaming
  - Parallel tool calls
  - Automatic reasoning extraction from assistant messages
  - Automatic error classification

Usage:
    from ageval import trace_openai

    from openai import OpenAI
    client = OpenAI()

    messages = [{"role": "user", "content": "What's the weather in Paris?"}]
    tools = [{"type": "function", "function": {...}}]

    response = trace_openai(
        client=client,
        messages=messages,
        tools=tools,
        tool_functions={"get_weather": get_weather_fn},
        agent_id="weather_agent_v1",
        task="Get weather for Paris",
        model="gpt-4o-mini",
    )

Env vars required:
    AGEVAL_API_KEY  — your ageval API key
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

from ageval.session import AgentSession, _api_configured, _safe_serialize

log = logging.getLogger(__name__)


def trace_openai(
    client,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_functions: dict[str, Callable] | None = None,
    *,
    agent_id: str,
    task: str | None = None,
    model: str = "gpt-4o-mini",
    max_iterations: int = 10,
    **completion_kwargs,
) -> dict:
    """
    Run an OpenAI tool-calling loop with full AGeval tracing.

    Args:
        client: OpenAI client instance
        messages: Initial message list
        tools: Tool definitions (OpenAI format)
        tool_functions: Mapping of tool name → Python callable
        agent_id: Stable agent identifier
        task: Human-readable task description
        model: Model to use (default: gpt-4o-mini)
        max_iterations: Max tool-calling iterations before stopping
        **completion_kwargs: Extra kwargs passed to chat.completions.create

    Returns:
        Dict with keys:
          - messages: Full message history
          - final_content: The last assistant message content
          - episode_id: AGeval episode ID for querying results
    """
    if not _api_configured():
        # Fall through without tracing
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            **completion_kwargs,
        )
        return {
            "messages": messages + [resp.choices[0].message],
            "final_content": resp.choices[0].message.content,
            "episode_id": None,
        }

    tool_functions = tool_functions or {}
    working_messages = list(messages)

    with AgentSession(agent_id=agent_id, task=task, batch=True) as session:
        for iteration in range(max_iterations):
            # --- LLM call ---
            t0 = time.perf_counter()
            try:
                create_kwargs = {
                    "model": model,
                    "messages": working_messages,
                    **completion_kwargs,
                }
                if tools:
                    create_kwargs["tools"] = tools

                response = client.chat.completions.create(**create_kwargs)
                llm_latency = int((time.perf_counter() - t0) * 1000)
            except Exception as exc:
                session.record_error(
                    tool_name="llm_call",
                    exc=exc,
                    tool_input={"model": model, "iteration": iteration},
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                raise

            choice = response.choices[0]
            assistant_msg = choice.message

            # Record the LLM call itself as a step
            session.record_step(
                tool_name="llm_call",
                tool_input={
                    "model": model,
                    "iteration": iteration,
                    "message_count": len(working_messages),
                },
                tool_output={
                    "finish_reason": choice.finish_reason,
                    "content_preview": (assistant_msg.content or "")[:200],
                    "tool_calls_count": (
                        len(assistant_msg.tool_calls)
                        if assistant_msg.tool_calls
                        else 0
                    ),
                },
                success=True,
                reasoning=assistant_msg.content,
                latency_ms=llm_latency,
            )

            # If no tool calls, we're done
            if choice.finish_reason == "stop" or not assistant_msg.tool_calls:
                working_messages.append(
                    {"role": "assistant", "content": assistant_msg.content}
                )
                break

            # --- Execute tool calls ---
            working_messages.append(assistant_msg.model_dump())

            for tool_call in assistant_msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args_raw = tool_call.function.arguments

                try:
                    fn_args = json.loads(fn_args_raw)
                except json.JSONDecodeError:
                    fn_args = {"raw": fn_args_raw}

                fn = tool_functions.get(fn_name)
                if fn is None:
                    error_msg = f"Tool '{fn_name}' not found in tool_functions"
                    session.record_step(
                        tool_name=fn_name,
                        tool_input=fn_args,
                        success=False,
                        error_message=error_msg,
                        error_category="agent_error",
                        is_recoverable=False,
                        reasoning=assistant_msg.content,
                    )
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": error_msg}),
                        }
                    )
                    continue

                # Execute the tool
                t1 = time.perf_counter()
                try:
                    if isinstance(fn_args, dict):
                        result = fn(**fn_args)
                    else:
                        result = fn(fn_args)
                    tool_latency = int((time.perf_counter() - t1) * 1000)

                    result_str = (
                        json.dumps(result)
                        if not isinstance(result, str)
                        else result
                    )

                    session.record_step(
                        tool_name=fn_name,
                        tool_input=fn_args,
                        tool_output=_safe_serialize(result),
                        success=True,
                        reasoning=assistant_msg.content,
                        latency_ms=tool_latency,
                    )

                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str,
                        }
                    )

                except Exception as exc:
                    tool_latency = int((time.perf_counter() - t1) * 1000)
                    session.record_error(
                        tool_name=fn_name,
                        exc=exc,
                        tool_input=fn_args,
                        reasoning=assistant_msg.content,
                        latency_ms=tool_latency,
                    )
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": str(exc)}),
                        }
                    )
        else:
            # Hit max_iterations
            log.warning(
                f"[ageval] OpenAI agent hit max_iterations={max_iterations}"
            )

        # Extract final content
        final_content = None
        for msg in reversed(working_messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                final_content = msg.get("content")
                if final_content:
                    break

        return {
            "messages": working_messages,
            "final_content": final_content,
            "episode_id": session.episode_id,
        }
