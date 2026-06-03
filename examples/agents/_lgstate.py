"""
examples/agents/_lgstate.py

A shared, correctly-resolvable LangGraph message state plus small helpers that
every LangGraph example agent reuses.

Why this module exists: the example agents use `from __future__ import
annotations`, which turns every annotation into a *string* (a forward ref).
LangGraph calls `typing.get_type_hints()` on the state schema and evaluates
those strings against the schema's module globals. If the state's
`Annotated[list, add_messages]` is declared inside a function (where
`add_messages`/`Annotated` aren't module globals), resolution fails with
`NameError`.

Building the TypedDict with the *functional* `TypedDict("State", {...})` form
stores the real type objects (not deferred strings), so `get_type_hints`
resolves cleanly regardless of `from __future__ import annotations`. We expose
that one canonical `MessagesState` for all LangGraph agents.

This is itself a small AGeval-relevant lesson: agent frameworks have sharp
edges (type-hint evaluation, reducers, checkpoints) and AGeval has to trace
correctly across all of them.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

# Functional TypedDict form → annotations are concrete objects, so LangGraph's
# get_type_hints() never has to re-evaluate a deferred string. One state type,
# reused by every LangGraph example.
MessagesState = TypedDict("MessagesState", {"messages": Annotated[list, add_messages]})


def make_tool_node(tools_by_name: dict, on_call=None):
    """Build a LangGraph tool node that executes the model's tool calls.

    `on_call(name, args, result, ok, error)` is an optional callback fired for
    every tool execution — the example agents use it to mirror each call into an
    AGeval AgentSession. Errors are caught and returned as tool messages (so the
    graph can recover) AND surfaced through the callback as failures.
    """
    from langchain_core.messages import ToolMessage

    def tool_node(state) -> dict:
        last = state["messages"][-1]
        out = []
        for call in getattr(last, "tool_calls", []) or []:
            name, args, call_id = call["name"], call.get("args", {}), call["id"]
            tool = tools_by_name.get(name)
            if tool is None:
                msg = f"unknown tool {name!r}"
                if on_call:
                    on_call(name, args, None, False, msg)
                out.append(ToolMessage(content=msg, tool_call_id=call_id, status="error"))
                continue
            try:
                result = tool.invoke(args)
                if on_call:
                    on_call(name, args, result, True, None)
                out.append(ToolMessage(content=str(result), tool_call_id=call_id))
            except Exception as exc:  # keep the graph alive; record the failure
                if on_call:
                    on_call(name, args, None, False, f"{type(exc).__name__}: {exc}")
                out.append(ToolMessage(content=f"error: {exc}", tool_call_id=call_id, status="error"))
        return {"messages": out}

    return tool_node


def last_text(result: dict) -> str:
    """Pull the final assistant text out of a LangGraph result dict."""
    msgs = result.get("messages") if isinstance(result, dict) else None
    if not msgs:
        return ""
    final = msgs[-1]
    return getattr(final, "content", str(final))
