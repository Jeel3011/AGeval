"""
episodic_sdk.py

The core SDK. StepWriter and JobPusher POST to the ingestion API.
Users only need ONE env var:
    AGEVAL_API_KEY=ageval-sk-xxxxxxxx

Everything else is automatic.

Changes from v1:
  - Thread-safe step_index via threading.Lock (safe for parallel tool calls)
  - async_episodic_trace uses asyncio.to_thread — no event-loop blocking
  - BatchStepWriter collects steps and flushes in a single HTTP POST
  - EpisodeSession supports batched and non-batched modes
"""

from __future__ import annotations

import re
import time
import uuid
import asyncio
import functools
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
_API_BASE = "https://ageval-production.up.railway.app"


def _get_api_base() -> str:
    import os
    return os.environ.get("AGEVAL_API_URL", _API_BASE).rstrip("/")


def _get_api_key() -> str:
    import os
    key = os.environ.get("AGEVAL_API_KEY", "")
    if not key:
        raise RuntimeError("AGEVAL_API_KEY not set. Get a key from ageval.")
    return key


def _post(path: str, payload: dict) -> dict:
    """POST to the ingestion API. Raises on HTTP error."""
    import urllib.request, json

    url  = f"{_get_api_base()}{path}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {_get_api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ageval API error {e.code}: {body}") from e


def _post_batch(path: str, payload: list[dict]) -> dict:
    """POST a list of records to a batch endpoint."""
    import urllib.request, json

    url  = f"{_get_api_base()}{path}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {_get_api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ageval API batch error {e.code}: {body}") from e


# ---------------------------------------------------------------------------
# 1. Error classification
# ---------------------------------------------------------------------------
class ErrorCategory(str, Enum):
    AGENT_ERROR = "agent_error"
    ENV_ERROR   = "env_error"
    UNKNOWN     = "unknown"


_ENV_EXCEPTION_TYPES = (
    "ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout",
    "HTTPError", "RequestException", "RateLimitError", "TooManyRequests",
    "ServiceUnavailableError", "GatewayTimeout", "OSError", "IOError", "TimeoutError",
)
_AGENT_EXCEPTION_TYPES = (
    "ValueError", "TypeError", "KeyError", "AttributeError",
    "AssertionError", "NotImplementedError", "JSONDecodeError", "ValidationError",
)
_ENV_MSG = [
    r"timeout", r"timed out", r"connection (refused|reset|aborted)",
    r"rate limit", r"429", r"503", r"502", r"network (error|unreachable)",
    r"ssl", r"dns", r"host not found",
]
_AGENT_MSG = [
    r"invalid (argument|parameter|input)", r"unexpected (type|value|key)",
    r"missing (field|key|parameter)", r"not (found|supported|implemented)",
    r"cannot parse", r"failed to decode",
]


class ErrorClassifier:
    @classmethod
    def classify(cls, exc: Exception) -> tuple[ErrorCategory, bool]:
        name = type(exc).__name__
        msg  = str(exc).lower()
        if name in _ENV_EXCEPTION_TYPES:
            return ErrorCategory.ENV_ERROR, True
        if name in _AGENT_EXCEPTION_TYPES:
            return ErrorCategory.AGENT_ERROR, False
        for p in _ENV_MSG:
            if re.search(p, msg, re.IGNORECASE):
                return ErrorCategory.ENV_ERROR, True
        for p in _AGENT_MSG:
            if re.search(p, msg, re.IGNORECASE):
                return ErrorCategory.AGENT_ERROR, False
        return ErrorCategory.UNKNOWN, True


# ---------------------------------------------------------------------------
# 2. Reasoning extractor
# ---------------------------------------------------------------------------
class ReasoningExtractor:
    """Extract reasoning/chain-of-thought from various LLM output formats."""

    # XML-style tags: <reasoning>...</reasoning> or <thinking>...</thinking>
    _TAG_RE = re.compile(
        r"<(?:reasoning|thinking)[^>]*>(.*?)</(?:reasoning|thinking)>",
        re.DOTALL | re.IGNORECASE,
    )
    # ReACT-style: Thought: / Reasoning: / Think:
    _REACT_RE = re.compile(
        r"^(?:thought|reasoning|think)[:\s]+(.+?)(?=\n(?:action|tool|observation)|$)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    # OpenAI function-call style: content before the first tool_call
    _OPENAI_RE = re.compile(
        r"^(.+?)(?=\n(?:```|\{\s*\"type\"\s*:|function_call|tool_call))",
        re.DOTALL,
    )

    @classmethod
    def extract(cls, llm_output: Optional[str]) -> Optional[str]:
        if not llm_output or not llm_output.strip():
            return None
        # 1. XML/tag format (<reasoning> or <thinking>)
        m = cls._TAG_RE.search(llm_output)
        if m:
            return m.group(1).strip() or None
        # 2. ReACT format (Thought: / Think:)
        m = cls._REACT_RE.search(llm_output)
        if m:
            extracted = m.group(1).strip()
            return extracted or None
        # 3. OpenAI content before tool call block
        m = cls._OPENAI_RE.search(llm_output)
        if m:
            text = m.group(1).strip()
            # Only use if it looks like a reasoning sentence (>20 chars, no JSON)
            if len(text) > 20 and not text.startswith("{"):
                return text
        return None


# ---------------------------------------------------------------------------
# 3. StepWriter (single write)
# ---------------------------------------------------------------------------
class StepWriter:
    def write(self, record: dict) -> None:
        _post("/steps", record)


# ---------------------------------------------------------------------------
# 4. BatchStepWriter — collects steps, flushes all at once
# ---------------------------------------------------------------------------
class BatchStepWriter:
    """
    Accumulates step records in memory and flushes them in a single
    POST /steps/batch call. Designed for EpisodeSession usage where
    all steps are flushed at the end of the episode.

    Thread-safe for concurrent tool calls.
    """

    def __init__(self):
        self._steps: list[dict] = []
        self._lock  = threading.Lock()

    def add(self, record: dict) -> None:
        with self._lock:
            self._steps.append(record)

    def flush(self, swallow_errors: bool = True) -> None:
        with self._lock:
            steps = list(self._steps)
            self._steps.clear()

        if not steps:
            return
        try:
            _post_batch("/steps/batch", steps)
        except Exception as exc:
            if not swallow_errors:
                raise
            import sys
            print(f"[ageval] WARNING: batch flush failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 5. Thread-safe step index counter
# ---------------------------------------------------------------------------
class _AtomicCounter:
    """Thread-safe integer counter."""
    def __init__(self, start: int = 0):
        self._value = start
        self._lock  = threading.Lock()

    def next(self) -> int:
        with self._lock:
            v = self._value
            self._value += 1
            return v

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


# ---------------------------------------------------------------------------
# 6. @episodic_trace  (sync)
# ---------------------------------------------------------------------------
def episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
    _batch_writer: Optional[BatchStepWriter] = None,
):
    """
    Decorator that wraps a sync tool function.

    Args:
        episode_id          : episode this step belongs to
        step_index          : position in the episode (0-based)
        llm_output          : raw LLM text to extract reasoning from
        swallow_write_errors: if True, write failures print a warning
                              instead of crashing the agent
        _batch_writer       : optional BatchStepWriter; if provided,
                              step is buffered instead of posted immediately
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = _batch_writer

            t0             = time.perf_counter()
            success        = False
            tool_output    = None
            error_message  = None
            error_category = None
            is_recoverable = None

            try:
                result      = fn(*args, **kwargs)
                success     = True
                tool_output = _safe_serialize(result)
                return result
            except Exception as exc:
                cat, recoverable = ErrorClassifier.classify(exc)
                error_message    = str(exc)
                error_category   = cat.value
                is_recoverable   = recoverable
                raise
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                record = {
                    "episode_id"    : episode_id,
                    "step_index"    : step_index,
                    "tool_name"     : tool_name,
                    "tool_input"    : tool_input,
                    "tool_output"   : tool_output,
                    "success"       : success,
                    "error_message" : error_message,
                    "error_category": error_category,
                    "is_recoverable": is_recoverable,
                    "reasoning"     : reasoning,
                    "latency_ms"    : latency_ms,
                    "created_at"    : datetime.now(timezone.utc).isoformat(),
                }
                try:
                    if writer is not None:
                        writer.add(record)
                    else:
                        StepWriter().write(record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    import sys
                    print(f"[ageval] WARNING: step write failed: {write_exc}", file=sys.stderr)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 7. async_episodic_trace — uses asyncio.to_thread to avoid blocking
# ---------------------------------------------------------------------------
def async_episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
    _batch_writer: Optional[BatchStepWriter] = None,
):
    """
    Async variant of episodic_trace.
    The step write is offloaded to a thread so it never blocks the event loop.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = _batch_writer

            t0             = time.perf_counter()
            success        = False
            tool_output    = None
            error_message  = None
            error_category = None
            is_recoverable = None

            try:
                result      = await fn(*args, **kwargs)
                success     = True
                tool_output = _safe_serialize(result)
                return result
            except Exception as exc:
                cat, recoverable = ErrorClassifier.classify(exc)
                error_message    = str(exc)
                error_category   = cat.value
                is_recoverable   = recoverable
                raise
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                record = {
                    "episode_id"    : episode_id,
                    "step_index"    : step_index,
                    "tool_name"     : tool_name,
                    "tool_input"    : tool_input,
                    "tool_output"   : tool_output,
                    "success"       : success,
                    "error_message" : error_message,
                    "error_category": error_category,
                    "is_recoverable": is_recoverable,
                    "reasoning"     : reasoning,
                    "latency_ms"    : latency_ms,
                    "created_at"    : datetime.now(timezone.utc).isoformat(),
                }
                # Await the write directly — ensure_future was dropping writes
                # on short-lived event loops. Use asyncio.to_thread for blocking I/O.
                try:
                    if writer is not None:
                        writer.add(record)
                    else:
                        await asyncio.to_thread(StepWriter().write, record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    import sys
                    print(f"[ageval] WARNING: async step write failed: {write_exc}", file=sys.stderr)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 8. JobPusher
# ---------------------------------------------------------------------------
class JobPusher:
    def push(
        self,
        episode_id: str,
        run_id: str,
        agent_id: str,
        task: Optional[str] = None,
    ) -> str:
        resp = _post("/jobs", {
            "episode_id": episode_id,
            "run_id"    : run_id,
            "agent_id"  : agent_id,
            "task"      : task,
        })
        return resp.get("episode_id", episode_id)


# ---------------------------------------------------------------------------
# 9. EpisodeSession — high-level context manager
# ---------------------------------------------------------------------------
class EpisodeSession:
    """
    High-level session that manages episode lifecycle.

    Usage (basic):
        session = EpisodeSession(agent_id="my_agent", task="do something")
        session.start()
        traced_fn = session.trace(my_tool_fn, reasoning=llm_text)
        result = traced_fn(arg1, arg2)
        session.finish()

    Usage (context manager):
        with EpisodeSession(agent_id="my_agent") as session:
            session.start()
            ...

    Usage (batched — fewer HTTP calls):
        session = EpisodeSession(agent_id="my_agent", batch=True)
        session.start()
        traced_fn = session.trace(my_tool_fn)
        result = traced_fn(...)
        session.finish()   # flushes all steps in one request
    """

    def __init__(
        self,
        agent_id: str,
        task: str | None = None,
        swallow_write_errors: bool = True,
        batch: bool = False,
    ):
        self.episode_id           = new_episode_id()
        self.agent_id             = agent_id
        self.task                 = task
        self.swallow_write_errors = swallow_write_errors
        self._counter             = _AtomicCounter()        # thread-safe
        self._langsmith_run_id    = None
        self._batch_writer        = BatchStepWriter() if batch else None

    def start(self, langsmith_run_id: str | None = None) -> "EpisodeSession":
        self._langsmith_run_id = langsmith_run_id or "pending"
        _post("/episodes", {
            "episode_id": self.episode_id,
            "agent_id"  : self.agent_id,
            "task"      : self.task,
        })
        return self

    def set_run_id(self, run_id: str) -> None:
        self._langsmith_run_id = run_id

    def trace(self, fn: Callable, reasoning: str | None = None) -> Callable:
        """Wrap a tool function with episodic tracing. Returns the wrapped function."""
        step_index = self._counter.next()
        return episodic_trace(
            episode_id           = self.episode_id,
            step_index           = step_index,
            llm_output           = reasoning,
            swallow_write_errors = self.swallow_write_errors,
            _batch_writer        = self._batch_writer,
        )(fn)

    def finish(self) -> str:
        """Flush any buffered steps, then push the job to the merge queue."""
        if self._batch_writer is not None:
            self._batch_writer.flush(swallow_errors=self.swallow_write_errors)

        return JobPusher().push(
            episode_id = self.episode_id,
            run_id     = self._langsmith_run_id or "none",
            agent_id   = self.agent_id,
            task       = self.task,
        )

    def __enter__(self) -> "EpisodeSession":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.finish()
        return False  # do not suppress exceptions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_episode_id() -> str:
    return f"ep_{uuid.uuid4().hex[:16]}"


def _safe_serialize(value: Any) -> Any:
    import json
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)