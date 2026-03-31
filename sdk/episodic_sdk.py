"""
episodic_sdk.py
Tool wrapper SDK for agent evaluation pipeline.

Components:
  1. ErrorClassifier       — decides agent_error vs env_error vs unknown
  2. ReasoningExtractor    — pulls CoT from LLM output, with fallback
  3. @episodic_trace        — decorator: wraps any tool, captures full step record
  4. StepWriter            — writes one row to episode_steps immediately after each call
  5. JobPusher             — pushes one row to episode_jobs when agent run finishes

Usage:
    from episodic_sdk import episodic_trace, JobPusher

    @episodic_trace(episode_id="ep_abc123", step_index=0)
    def search_web(query: str) -> str:
        ...

    # At agent run end:
    JobPusher().push(episode_id="ep_abc123", run_id="ls_run_xyz", agent_id="agent_v1", task="summarize X")
"""

from __future__ import annotations

import re
import time
import uuid
import functools
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Supabase client — lazy import so SDK can be imported without the dep
# ---------------------------------------------------------------------------
def _get_supabase():
    try:
        import os
        from supabase import create_client
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(url, key)
    except KeyError as e:
        raise RuntimeError(f"Missing env var: {e}") from e
    except ImportError:
        raise RuntimeError("supabase-py not installed. Run: pip install supabase")


# ---------------------------------------------------------------------------
# 1. Error classification
# ---------------------------------------------------------------------------
class ErrorCategory(str, Enum):
    AGENT_ERROR   = "agent_error"    # Bad input, wrong tool choice, logic bug in agent
    ENV_ERROR     = "env_error"      # Network, timeout, third-party API down, rate limit
    UNKNOWN       = "unknown"        # Catch-all when we genuinely can't tell


# These are the concrete rules. If you change them, change the docstring too.
_ENV_EXCEPTION_TYPES = (
    # Network / HTTP
    "ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout",
    "HTTPError", "RequestException",
    # Rate limits / quota
    "RateLimitError", "TooManyRequests",
    # Third-party infra
    "ServiceUnavailableError", "GatewayTimeout",
    # OS / IO
    "OSError", "IOError", "TimeoutError",
)

_AGENT_EXCEPTION_TYPES = (
    # Bad inputs / contract violations
    "ValueError", "TypeError", "KeyError", "AttributeError",
    "AssertionError", "NotImplementedError",
    # Parsing failures (agent produced malformed output)
    "JSONDecodeError", "ValidationError",
)

_ENV_MESSAGE_PATTERNS = [
    r"timeout", r"timed out", r"connection (refused|reset|aborted)",
    r"rate limit", r"429", r"503", r"502", r"network (error|unreachable)",
    r"ssl", r"dns", r"host not found",
]

_AGENT_MESSAGE_PATTERNS = [
    r"invalid (argument|parameter|input)",
    r"unexpected (type|value|key)",
    r"missing (field|key|parameter)",
    r"not (found|supported|implemented)",
    r"cannot parse", r"failed to decode",
]


class ErrorClassifier:
    """
    Classify an exception into agent_error, env_error, or unknown.

    Classification order:
      1. Exception type name (most reliable)
      2. Exception message patterns (fallback)
      3. unknown (honest — don't guess)
    """

    @classmethod
    def classify(cls, exc: Exception) -> tuple[ErrorCategory, bool]:
        """
        Returns (category, is_recoverable).

        is_recoverable:
          True  → env_error (retry makes sense)
          False → agent_error (retrying same call won't help)
          None  → unknown (queue retries it by default, but flag it)
        """
        exc_type = type(exc).__name__
        msg = str(exc).lower()

        if exc_type in _ENV_EXCEPTION_TYPES:
            return ErrorCategory.ENV_ERROR, True

        if exc_type in _AGENT_EXCEPTION_TYPES:
            return ErrorCategory.AGENT_ERROR, False

        for pattern in _ENV_MESSAGE_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return ErrorCategory.ENV_ERROR, True

        for pattern in _AGENT_MESSAGE_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                return ErrorCategory.AGENT_ERROR, False

        return ErrorCategory.UNKNOWN, True  # default: let queue retry once


# ---------------------------------------------------------------------------
# 2. Reasoning extractor
# ---------------------------------------------------------------------------
class ReasoningExtractor:
    """
    Pull the agent's CoT reasoning from LLM output before a tool call.

    Strategy (in order):
      1. Look for explicit <reasoning>...</reasoning> tags
      2. Look for a "Thought:" or "Reasoning:" prefix line (ReAct style)
      3. Return None — write null to DB, don't invent anything

    Call .extract(llm_output) and attach the result to the step record.
    If your framework provides the pre-tool LLM text, pass it in.
    If not (framework swallows it), pass None — this field will be null.
    """

    # Pattern 1: explicit XML-ish tag
    _TAG_RE = re.compile(
        r"<reasoning[^>]*>(.*?)</reasoning>",
        re.DOTALL | re.IGNORECASE,
    )

    # Pattern 2: ReAct-style "Thought:" prefix
    _REACT_RE = re.compile(
        r"^(?:thought|reasoning|think)[:\s]+(.+?)(?=\n(?:action|tool|observation)|$)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )

    @classmethod
    def extract(cls, llm_output: Optional[str]) -> Optional[str]:
        if not llm_output:
            return None

        m = cls._TAG_RE.search(llm_output)
        if m:
            return m.group(1).strip()

        m = cls._REACT_RE.search(llm_output)
        if m:
            return m.group(1).strip()

        return None  # honest null — don't fabricate reasoning


# ---------------------------------------------------------------------------
# 3. Step writer
# ---------------------------------------------------------------------------
class StepWriter:
    """
    Write one row to episode_steps immediately after each tool call.
    The merger reads these rows later; it does NOT re-derive them from LangSmith.

    Schema expected in Supabase:
        episode_steps (
            id              uuid primary key default gen_random_uuid(),
            episode_id      text not null,
            step_index      int  not null,
            tool_name       text not null,
            tool_input      jsonb,
            tool_output     jsonb,
            success         boolean not null,
            error_message   text,
            error_category  text,        -- 'agent_error' | 'env_error' | 'unknown'
            is_recoverable  boolean,
            reasoning       text,
            latency_ms      int,
            created_at      timestamptz default now()
        )
    """

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_supabase()
        return self._client

    def write(self, record: dict) -> None:
        """
        Insert one step record. Raises on Supabase error — let the caller
        decide whether to swallow it (don't let observability break the agent).
        """
        resp = self.client.table("episode_steps").insert(record).execute()
        if hasattr(resp, "error") and resp.error:
            raise RuntimeError(f"StepWriter insert failed: {resp.error}")


# ---------------------------------------------------------------------------
# 4. @episodic_trace decorator
# ---------------------------------------------------------------------------
def episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
):
    """
    Decorator factory. Wraps any sync tool function.

    Args:
        episode_id          : The episode this step belongs to.
        step_index          : Position of this tool call in the run (0-based).
        llm_output          : The LLM text that preceded this tool call.
                              Pass it in if your framework exposes it.
                              If not, leave None — reasoning will be null.
        swallow_write_errors: If True (default), a Supabase write failure
                              is logged but doesn't crash the agent.
                              Set False in tests to surface errors.

    Example:
        reasoning_text = agent.last_llm_output  # framework-specific

        @episodic_trace(episode_id=ep_id, step_index=i, llm_output=reasoning_text)
        def search_web(query: str) -> str:
            return requests.get(f"https://api.example.com?q={query}").text

    For async tools, use @async_episodic_trace below.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = StepWriter()

            t0 = time.perf_counter()
            success        = False
            tool_output    = None
            error_message  = None
            error_category = None
            is_recoverable = None

            try:
                result     = fn(*args, **kwargs)
                success    = True
                tool_output = _safe_serialize(result)
                return result

            except Exception as exc:
                cat, recoverable  = ErrorClassifier.classify(exc)
                error_message     = str(exc)
                error_category    = cat.value
                is_recoverable    = recoverable
                # Re-raise so the agent's own error handling still fires
                raise

            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)

                record = {
                    "episode_id"     : episode_id,
                    "step_index"     : step_index,
                    "tool_name"      : tool_name,
                    "tool_input"     : tool_input,
                    "tool_output"    : tool_output,
                    "success"        : success,
                    "error_message"  : error_message,
                    "error_category" : error_category,
                    "is_recoverable" : is_recoverable,
                    "reasoning"      : reasoning,
                    "latency_ms"     : latency_ms,
                    "created_at"     : datetime.now(timezone.utc).isoformat(),
                }

                try:
                    writer.write(record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    # Don't crash the agent over observability failures
                    import sys
                    print(
                        f"[episodic_sdk] WARNING: step write failed for "
                        f"{tool_name} (step {step_index}): {write_exc}",
                        file=sys.stderr,
                    )

        return wrapper
    return decorator


def async_episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
):
    """Same as episodic_trace but for async tool functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = StepWriter()

            t0 = time.perf_counter()
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
                cat, recoverable  = ErrorClassifier.classify(exc)
                error_message     = str(exc)
                error_category    = cat.value
                is_recoverable    = recoverable
                raise

            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)

                record = {
                    "episode_id"     : episode_id,
                    "step_index"     : step_index,
                    "tool_name"      : tool_name,
                    "tool_input"     : tool_input,
                    "tool_output"    : tool_output,
                    "success"        : success,
                    "error_message"  : error_message,
                    "error_category" : error_category,
                    "is_recoverable" : is_recoverable,
                    "reasoning"      : reasoning,
                    "latency_ms"     : latency_ms,
                    "created_at"     : datetime.now(timezone.utc).isoformat(),
                }

                try:
                    writer.write(record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    import sys
                    print(
                        f"[episodic_sdk] WARNING: async step write failed for "
                        f"{tool_name} (step {step_index}): {write_exc}",
                        file=sys.stderr,
                    )

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 5. Job pusher
# ---------------------------------------------------------------------------
class JobPusher:
    """
    Push one row to episode_jobs when the agent run finishes.
    The merger worker polls this table.

    Schema expected in Supabase:
        episode_jobs (
            id            uuid primary key default gen_random_uuid(),
            episode_id    text not null unique,
            run_id        text not null,      -- LangSmith run ID
            agent_id      text not null,
            task          text,
            status        text not null default 'pending',
            retry_count   int  not null default 0,
            locked_at     timestamptz,
            error_message text,
            created_at    timestamptz default now()
        )
    """

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_supabase()
        return self._client

    def push(
        self,
        episode_id : str,
        run_id     : str,
        agent_id   : str,
        task       : Optional[str] = None,
    ) -> str:
        """
        Insert a job with status='pending'. Returns the job's UUID.

        Raises if the insert fails — this is critical path.
        A missing job means the merger never runs; you want to know immediately.
        """
        job_id = str(uuid.uuid4())
        record = {
            "id"         : job_id,
            "episode_id" : episode_id,
            "run_id"     : run_id,
            "agent_id"   : agent_id,
            "task"       : task,
            "status"     : "pending",
            "retry_count": 0,
            "created_at" : datetime.now(timezone.utc).isoformat(),
        }

        resp = self.client.table("episode_jobs").insert(record).execute()
        if hasattr(resp, "error") and resp.error:
            raise RuntimeError(f"JobPusher insert failed: {resp.error}")

        return job_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _safe_serialize(value: Any) -> Any:
    """
    Convert tool output to something JSON-serializable for Supabase jsonb.
    Falls back to str(value) rather than crashing.
    """
    import json
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Convenience: generate a fresh episode_id
# ---------------------------------------------------------------------------
def new_episode_id() -> str:
    """Generate a fresh episode ID. Use this at the start of each agent run."""
    return f"ep_{uuid.uuid4().hex[:16]}"

class EpisodeSession:
    """
    Manages one agent run. Tracks step index automatically.
    Use as a context manager or call .finish() manually.

    Example:
        with EpisodeSession(agent_id="my_agent", task="do X") as session:
            result = session.trace(search_web, reasoning="searching for X")("query")
            result = session.trace(parse_result)( result )
        # job is pushed automatically on __exit__
    """

    def __init__(
        self,
        agent_id            : str,
        task                : str | None = None,
        swallow_write_errors: bool = True,
    ):
        self.episode_id          = new_episode_id()
        self.agent_id            = agent_id
        self.task                = task
        self.swallow_write_errors= swallow_write_errors
        self._step_index         = 0
        self._client             = None
        self._langsmith_run_id   = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_supabase()
        return self._client

    def start(self, langsmith_run_id: str | None = None):
        """
        Call this at the start of the agent run.
        Creates the stub episodes row so step writes don't fail the FK.
        """
        self._langsmith_run_id = langsmith_run_id or "pending"
        self.client.table("episodes").insert({
            "episode_id": self.episode_id,
            "agent_id"  : self.agent_id,
            "run_id"    : self._langsmith_run_id,
            "task"      : self.task,
        }).execute()
        return self

    def set_run_id(self, run_id: str):
        """Update the run_id once you have it from LangSmith."""
        self._langsmith_run_id = run_id
        self.client.table("episodes").update(
            {"run_id": run_id}
        ).eq("episode_id", self.episode_id).execute()

    def trace(self, fn: Callable, reasoning: str | None = None) -> Callable:
        """
        Wrap a tool function for this step. Auto-increments step_index.
        Call the returned function immediately with the tool's arguments.

        session.trace(search_web, reasoning="need to find X")("my query")
        """
        wrapped = episodic_trace(
            episode_id          = self.episode_id,
            step_index          = self._step_index,
            llm_output          = reasoning,
            swallow_write_errors= self.swallow_write_errors,
        )(fn)
        self._step_index += 1
        return wrapped

    def finish(self):
        """Push the job to the queue. Worker picks it up and merges."""
        if not self._langsmith_run_id or self._langsmith_run_id == "pending":
            raise RuntimeError(
                "run_id not set. Call session.set_run_id(run_id) "
                "before finishing."
            )
        return JobPusher().push(
            episode_id = self.episode_id,
            run_id     = self._langsmith_run_id,
            agent_id   = self.agent_id,
            task       = self.task,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._langsmith_run_id and self._langsmith_run_id != "pending":
            self.finish()
        return False  # don't suppress exceptions    