"""
ageval/session.py

Framework-agnostic EpisodeSession — works with ANY agent type.

This is the universal entry point for evaluating agents that are NOT
LangGraph/LangChain. Users call record_step() for each tool action
their agent takes, and AGeval handles scoring automatically.

Works with:
  - OpenAI function calling
  - Anthropic tool use
  - CrewAI agents
  - AutoGen agents
  - Any custom agent loop
  - Even non-LLM agents (RPA, rule-based, etc.)

Usage:
    from ageval import AgentSession

    with AgentSession(agent_id="my_agent", task="book a flight") as session:
        # Your agent does its thing...
        result = my_tool(args)
        session.record_step(
            tool_name="search_flights",
            tool_input={"destination": "Paris"},
            tool_output=result,
            success=True,
            reasoning="User wants to go to Paris, searching flights",
        )

    # On exit: steps are flushed, job is pushed, scoring runs automatically.

Env vars required:
    AGEVAL_API_KEY  — your ageval API key (the only thing you need)

Optional:
    AGEVAL_API_URL  — override the API base URL
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API helpers (self-contained — no dependency on tracer.py to avoid cycles)
# ---------------------------------------------------------------------------
def _get_api_base() -> str:
    return os.environ.get(
        "AGEVAL_API_URL",
        "https://ageval-production.up.railway.app",
    ).rstrip("/")


def _get_api_key() -> str:
    k = os.environ.get("AGEVAL_API_KEY", "")
    if not k:
        raise RuntimeError(
            "AGEVAL_API_KEY not set. Get a key at https://github.com/Jeel3011/AGeval"
        )
    return k


def _api_configured() -> bool:
    return bool(os.environ.get("AGEVAL_API_KEY"))


def _post(path: str, payload: dict | list, *, swallow: bool = True) -> dict | None:
    """POST JSON to the ageval API."""
    import urllib.request
    import urllib.error

    try:
        url = f"{_get_api_base()}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_get_api_key()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        if swallow:
            log.warning(f"[ageval] API post to {path} failed: {exc}")
            return None
        raise


# ---------------------------------------------------------------------------
# Error classification (framework-agnostic)
# ---------------------------------------------------------------------------
_ENV_ERRORS = {
    "ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout",
    "HTTPError", "RequestException", "RateLimitError", "OSError",
    "IOError", "TimeoutError", "ServiceUnavailableError",
}
_AGENT_ERRORS = {
    "ValueError", "TypeError", "KeyError", "AttributeError",
    "AssertionError", "NotImplementedError", "JSONDecodeError",
    "ValidationError",
}
_ENV_PATTERNS = [
    r"time(?:out|d out)", r"connection (refused|reset)", r"rate limit",
    r"429", r"503", r"502", r"ssl", r"dns",
]
_AGENT_PATTERNS = [
    r"invalid (argument|parameter|input)", r"missing (field|key)",
    r"cannot parse", r"failed to decode",
]


def classify_error(exc: Exception) -> tuple[str, bool]:
    """
    Classify an exception as agent_error, env_error, or unknown.
    Returns (category, is_recoverable).

    Public API — users can call this from their own error handlers.
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in _ENV_ERRORS:
        return "env_error", True
    if name in _AGENT_ERRORS:
        return "agent_error", False
    for p in _ENV_PATTERNS:
        if re.search(p, msg, re.IGNORECASE):
            return "env_error", True
    for p in _AGENT_PATTERNS:
        if re.search(p, msg, re.IGNORECASE):
            return "agent_error", False
    return "unknown", True


# ---------------------------------------------------------------------------
# Safe serialization
# ---------------------------------------------------------------------------
def _safe_serialize(value: Any) -> Any:
    """Ensure a value is JSON-serializable."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# AgentSession — the main class
# ---------------------------------------------------------------------------
class AgentSession:
    """
    Framework-agnostic session for evaluating any agent.

    Records tool calls as steps, flushes them to the AGeval API,
    and triggers automatic scoring when the session ends.

    Thread-safe: multiple threads can call record_step() concurrently.

    Modes:
        - Context manager (recommended): steps flushed on __exit__
        - Manual: call start() / finish() explicitly
        - Batch: accumulates steps in memory, one POST at the end

    Args:
        agent_id: Stable name for your agent (e.g. "trip_planner_v2")
        task: Human-readable description of what this run is doing
        batch: If True, buffer steps and flush in one POST at the end
        metadata: Optional dict of arbitrary metadata (stored with episode)
    """

    def __init__(
        self,
        agent_id: str,
        task: str | None = None,
        batch: bool = True,
        metadata: dict | None = None,
    ):
        self.episode_id = f"ep_{uuid.uuid4().hex[:16]}"
        self.agent_id = agent_id
        self.task = task
        self.metadata = metadata or {}
        self._batch = batch
        self._steps: list[dict] = []
        self._lock = threading.Lock()
        self._step_counter = 0
        self._started = False
        self._finished = False
        self._start_time: float | None = None

    def start(self) -> "AgentSession":
        """Create the episode on the server. Called automatically by __enter__."""
        if self._started:
            return self

        if not _api_configured():
            log.warning("[ageval] AGEVAL_API_KEY not set — session will not record")
            self._started = True
            return self

        _post(
            "/episodes",
            {
                "episode_id": self.episode_id,
                "agent_id": self.agent_id,
                "task": self.task,
            },
            swallow=False,
        )
        self._started = True
        self._start_time = time.perf_counter()
        log.info(f"[ageval] Session started: {self.episode_id}")
        return self

    def record_step(
        self,
        tool_name: str,
        tool_input: Any = None,
        tool_output: Any = None,
        success: bool = True,
        error_message: str | None = None,
        error_category: str | None = None,
        is_recoverable: bool | None = None,
        reasoning: str | None = None,
        latency_ms: int | None = None,
    ) -> int:
        """
        Record one tool call / action step.

        Args:
            tool_name: Name of the tool/function called
            tool_input: What was passed to the tool (any JSON-serializable value)
            tool_output: What the tool returned (any JSON-serializable value)
            success: Did the tool call succeed?
            error_message: Error message if failed
            error_category: 'agent_error' | 'env_error' | 'unknown'
            is_recoverable: Should the agent retry?
            reasoning: Why the agent made this call (chain of thought)
            latency_ms: How long the call took in milliseconds

        Returns:
            The step_index assigned to this step.
        """
        with self._lock:
            idx = self._step_counter
            self._step_counter += 1

        record = {
            "episode_id": self.episode_id,
            "step_index": idx,
            "tool_name": tool_name,
            "tool_input": _safe_serialize(tool_input),
            "tool_output": _safe_serialize(tool_output),
            "success": success,
            "error_message": error_message,
            "error_category": error_category,
            "is_recoverable": is_recoverable,
            "reasoning": reasoning,
            "latency_ms": latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._batch:
            with self._lock:
                self._steps.append(record)
        else:
            _post("/steps", record, swallow=True)

        return idx

    def record_error(
        self,
        tool_name: str,
        exc: Exception,
        tool_input: Any = None,
        reasoning: str | None = None,
        latency_ms: int | None = None,
    ) -> int:
        """
        Convenience method: record a failed tool call from an exception.
        Automatically classifies the error.
        """
        cat, recoverable = classify_error(exc)
        return self.record_step(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=None,
            success=False,
            error_message=str(exc),
            error_category=cat,
            is_recoverable=recoverable,
            reasoning=reasoning,
            latency_ms=latency_ms,
        )

    def traced(
        self,
        fn: Callable,
        *,
        tool_name: str | None = None,
        reasoning: str | None = None,
    ) -> Callable:
        """
        Wrap a callable so it's automatically traced.

        Usage:
            search = session.traced(search_flights, reasoning="searching for flights")
            result = search("Paris")  # automatically recorded as a step

        Args:
            fn: The function to wrap
            tool_name: Override the tool name (default: fn.__name__)
            reasoning: Reasoning for this tool call
        """
        import functools

        name = tool_name or getattr(fn, "__name__", "unknown_tool")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                self.record_step(
                    tool_name=name,
                    tool_input=_safe_serialize({"args": list(args), "kwargs": kwargs}),
                    tool_output=_safe_serialize(result),
                    success=True,
                    reasoning=reasoning,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result
            except Exception as exc:
                self.record_error(
                    tool_name=name,
                    exc=exc,
                    tool_input=_safe_serialize({"args": list(args), "kwargs": kwargs}),
                    reasoning=reasoning,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                raise

        return wrapper

    def traced_async(
        self,
        fn: Callable,
        *,
        tool_name: str | None = None,
        reasoning: str | None = None,
    ) -> Callable:
        """Async version of traced(). Wraps an async callable."""
        import asyncio
        import functools

        name = tool_name or getattr(fn, "__name__", "unknown_tool")

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                self.record_step(
                    tool_name=name,
                    tool_input=_safe_serialize({"args": list(args), "kwargs": kwargs}),
                    tool_output=_safe_serialize(result),
                    success=True,
                    reasoning=reasoning,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result
            except Exception as exc:
                self.record_error(
                    tool_name=name,
                    exc=exc,
                    tool_input=_safe_serialize({"args": list(args), "kwargs": kwargs}),
                    reasoning=reasoning,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                raise

        return wrapper

    def finish(self) -> str:
        """
        Flush buffered steps and push the merge job.
        Called automatically by __exit__.
        Returns the episode_id.
        """
        if self._finished:
            return self.episode_id
        self._finished = True

        if not _api_configured():
            return self.episode_id

        # Flush batch steps
        if self._batch and self._steps:
            with self._lock:
                steps = list(self._steps)
                self._steps.clear()
            if steps:
                _post("/steps/batch", steps, swallow=True)

        # Push job (non-blocking)
        t = threading.Thread(
            target=_post,
            args=(
                "/jobs",
                {
                    "episode_id": self.episode_id,
                    "run_id": "none",
                    "agent_id": self.agent_id,
                    "task": self.task,
                },
            ),
            kwargs={"swallow": True},
            daemon=False,
        )
        t.start()

        log.info(
            f"[ageval] Session finished: {self.episode_id} "
            f"({self._step_counter} steps)"
        )
        return self.episode_id

    # Context manager support
    def __enter__(self) -> "AgentSession":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.finish()
        return False  # don't suppress exceptions


# ---------------------------------------------------------------------------
# trace_callable — universal wrapper for any function-based agent
# ---------------------------------------------------------------------------
def trace_callable(
    fn: Callable,
    *,
    args: tuple = (),
    kwargs: dict | None = None,
    agent_id: str,
    task: str | None = None,
) -> Any:
    """
    Wrap ANY callable (function, lambda, method) with episodic tracing.

    This is the simplest possible integration — one function call:

        from ageval import trace_callable

        result = trace_callable(
            my_agent_function,
            args=(user_query,),
            agent_id="my_agent_v1",
            task="answer the user's question",
        )

    The function is treated as a single-step episode (tool_name = fn.__name__).
    For multi-step agents, use AgentSession instead.
    """
    if not _api_configured():
        return fn(*args, **(kwargs or {}))

    with AgentSession(agent_id=agent_id, task=task) as session:
        traced_fn = session.traced(fn)
        return traced_fn(*args, **(kwargs or {}))
