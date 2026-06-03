"""
ageval/anthropic_tracer.py

Drop-in tracing for Anthropic (Claude) tool-use agents.

Wraps the Anthropic Messages API tool-use loop so every tool call your Claude
agent makes is automatically captured as an AGeval step — the same "one function
call" experience as ``trace_openai`` but for the Anthropic SDK.

Supports:
  - Claude tool use (``tool_use`` / ``tool_result`` content blocks)
  - Parallel tool calls in a single turn
  - Automatic reasoning extraction from the model's text blocks
  - Automatic error classification
  - Token-usage capture (input/output tokens) for cost metrics

Usage:
    from ageval import trace_anthropic
    from anthropic import Anthropic

    client = Anthropic()

    tools = [{
        "name": "get_weather",
        "description": "Get the weather for a city",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }]

    result = trace_anthropic(
        client=client,
        messages=[{"role": "user", "content": "Weather in Paris?"}],
        tools=tools,
        tool_functions={"get_weather": get_weather_fn},
        agent_id="weather_agent_v1",
        task="Get weather for Paris",
        model="claude-haiku-4-5-20251001",
    )
    # result["episode_id"] → query scores later

Env vars required:
    AGEVAL_API_KEY      — your ageval API key (to record)
    ANTHROPIC_API_KEY   — read by the Anthropic client (not by ageval)

If AGEVAL_API_KEY is unset, the loop runs normally with zero tracing overhead.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from ageval.session import AgentSession, _api_configured, _safe_serialize

log = logging.getLogger(__name__)


def _text_from_blocks(blocks: list) -> str:
    """Concatenate the text content blocks of an Anthropic message."""
    out = []
    for b in blocks:
        btype = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        if btype == "text":
            txt = getattr(b, "text", None) or (b.get("text") if isinstance(b, dict) else None)
            if txt:
                out.append(txt)
    return "\n".join(out).strip()


def _tool_uses_from_blocks(blocks: list) -> list:
    """Return the tool_use content blocks from an Anthropic message."""
    uses = []
    for b in blocks:
        btype = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        if btype == "tool_use":
            uses.append(b)
    return uses


def _block_attr(block: Any, name: str) -> Any:
    """Read an attribute from an SDK object or a plain dict block."""
    if isinstance(block, dict):
        return block.get(name)
    return getattr(block, name, None)


def trace_anthropic(
    client,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_functions: dict[str, Callable] | None = None,
    *,
    agent_id: str,
    task: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
    max_iterations: int = 10,
    max_tokens: int = 1024,
    system: str | None = None,
    **create_kwargs,
) -> dict:
    """
    Run an Anthropic (Claude) tool-use loop with full AGeval tracing.

    Args:
        client: Anthropic client instance (``Anthropic()``)
        messages: Initial message list (Anthropic format)
        tools: Tool definitions (Anthropic format — name/description/input_schema)
        tool_functions: Mapping of tool name → Python callable
        agent_id: Stable agent identifier
        task: Human-readable task description
        model: Claude model id (default: claude-haiku-4-5)
        max_iterations: Max tool-use iterations before stopping
        max_tokens: max_tokens for each Messages call
        system: optional system prompt
        **create_kwargs: extra kwargs passed to messages.create

    Returns:
        Dict with keys: messages, final_content, episode_id, usage
    """
    base_kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, **create_kwargs}
    if system:
        base_kwargs["system"] = system
    if tools:
        base_kwargs["tools"] = tools

    if not _api_configured():
        resp = client.messages.create(messages=messages, **base_kwargs)
        return {
            "messages": messages,
            "final_content": _text_from_blocks(resp.content),
            "episode_id": None,
            "usage": getattr(resp, "usage", None),
        }

    tool_functions = tool_functions or {}
    working_messages = list(messages)
    total_in_tokens = 0
    total_out_tokens = 0

    # Seed reasoning so an immediate tool call isn't left with empty reasoning.
    last_reasoning = ""
    for _m in reversed(messages):
        if isinstance(_m, dict) and _m.get("role") == "user" and _m.get("content"):
            content = _m["content"]
            if isinstance(content, str):
                text = content
            else:
                text = _text_from_blocks(content if isinstance(content, list) else [])
            if text:
                last_reasoning = f"task: {text[:200]}"
                break

    with AgentSession(agent_id=agent_id, task=task, batch=True) as session:
        for iteration in range(max_iterations):
            t0 = time.perf_counter()
            try:
                response = client.messages.create(messages=working_messages, **base_kwargs)
                llm_latency = int((time.perf_counter() - t0) * 1000)
            except Exception as exc:
                session.record_error(
                    tool_name="llm_call",
                    exc=exc,
                    tool_input={"model": model, "iteration": iteration},
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                raise

            usage = getattr(response, "usage", None)
            if usage is not None:
                total_in_tokens += getattr(usage, "input_tokens", 0) or 0
                total_out_tokens += getattr(usage, "output_tokens", 0) or 0

            blocks = response.content
            text_reasoning = _text_from_blocks(blocks)
            turn_reasoning = text_reasoning or last_reasoning
            if text_reasoning:
                last_reasoning = text_reasoning

            tool_uses = _tool_uses_from_blocks(blocks)

            # Record the LLM call itself as a step.
            session.record_step(
                tool_name="llm_call",
                tool_input={
                    "model": model,
                    "iteration": iteration,
                    "message_count": len(working_messages),
                },
                tool_output={
                    "stop_reason": getattr(response, "stop_reason", None),
                    "content_preview": text_reasoning[:200],
                    "tool_calls_count": len(tool_uses),
                    "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
                    "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
                },
                success=True,
                reasoning=text_reasoning or None,
                latency_ms=llm_latency,
            )

            # Append the assistant turn to the running history.
            working_messages.append(
                {"role": "assistant", "content": _serialize_blocks(blocks)}
            )

            # No tool calls → the agent is done.
            if not tool_uses:
                break

            # Execute every tool_use block and collect tool_result blocks.
            tool_results = []
            for tu in tool_uses:
                fn_name = _block_attr(tu, "name")
                fn_args = _block_attr(tu, "input") or {}
                tu_id = _block_attr(tu, "id")

                fn = tool_functions.get(fn_name)
                if fn is None:
                    error_msg = f"Tool '{fn_name}' not found in tool_functions"
                    session.record_step(
                        tool_name=fn_name or "unknown_tool",
                        tool_input=fn_args,
                        success=False,
                        error_message=error_msg,
                        error_category="agent_error",
                        is_recoverable=False,
                        reasoning=turn_reasoning,
                    )
                    tool_results.append(_tool_result(tu_id, {"error": error_msg}, is_error=True))
                    continue

                t1 = time.perf_counter()
                try:
                    result = fn(**fn_args) if isinstance(fn_args, dict) else fn(fn_args)
                    tool_latency = int((time.perf_counter() - t1) * 1000)
                    session.record_step(
                        tool_name=fn_name,
                        tool_input=fn_args,
                        tool_output=_safe_serialize(result),
                        success=True,
                        reasoning=turn_reasoning,
                        latency_ms=tool_latency,
                    )
                    tool_results.append(_tool_result(tu_id, result))
                except Exception as exc:
                    tool_latency = int((time.perf_counter() - t1) * 1000)
                    session.record_error(
                        tool_name=fn_name,
                        exc=exc,
                        tool_input=fn_args,
                        reasoning=turn_reasoning,
                        latency_ms=tool_latency,
                    )
                    tool_results.append(_tool_result(tu_id, {"error": str(exc)}, is_error=True))

            # Feed tool results back as the next user turn.
            working_messages.append({"role": "user", "content": tool_results})
        else:
            log.warning(f"[ageval] Anthropic agent hit max_iterations={max_iterations}")

        # Final assistant text.
        final_content = None
        for msg in reversed(working_messages):
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str):
                    final_content = content
                elif isinstance(content, list):
                    final_content = _text_from_blocks(content)
                if final_content:
                    break

        return {
            "messages": working_messages,
            "final_content": final_content,
            "episode_id": session.episode_id,
            "usage": {"input_tokens": total_in_tokens, "output_tokens": total_out_tokens},
        }


def _serialize_blocks(blocks: list) -> list[dict]:
    """Convert SDK content blocks into JSON-serializable dicts for history."""
    out = []
    for b in blocks:
        if isinstance(b, dict):
            out.append(b)
            continue
        btype = getattr(b, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": getattr(b, "text", "")})
        elif btype == "tool_use":
            out.append({
                "type": "tool_use",
                "id": getattr(b, "id", None),
                "name": getattr(b, "name", None),
                "input": getattr(b, "input", {}),
            })
        else:
            # Best effort for unknown block types.
            out.append(json.loads(b.model_dump_json()) if hasattr(b, "model_dump_json") else {"type": str(btype)})
    return out


def _tool_result(tool_use_id: Any, content: Any, *, is_error: bool = False) -> dict:
    """Build an Anthropic tool_result content block."""
    text = content if isinstance(content, str) else json.dumps(content)
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": text,
    }
    if is_error:
        block["is_error"] = True
    return block
