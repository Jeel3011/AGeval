"""
episodic_sdk.py  (updated)

The only change from before: StepWriter and JobPusher now POST to
your ingestion API instead of calling Supabase directly.

Users only need ONE env var:
    AGEVAL_API_KEY=ageval-sk-xxxxxxxx

That's it. No Supabase URL, no service key, no LangSmith key.

Everything else (ErrorClassifier, ReasoningExtractor, episodic_trace,
async_episodic_trace, EpisodeSession) is unchanged.
"""

from __future__ import annotations

import re
import time
import uuid
import functools
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# API client — replaces Supabase client
# ---------------------------------------------------------------------------
_API_BASE = "https://ageval-production.up.railway.app"  # set AGEVAL_API_URL to override


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
    import urllib.request, json, os

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
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ageval API error {e.code}: {body}") from e


# ---------------------------------------------------------------------------
# 1. Error classification  (unchanged)
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
# 2. Reasoning extractor  (unchanged)
# ---------------------------------------------------------------------------
class ReasoningExtractor:
    _TAG_RE = re.compile(r"<reasoning[^>]*>(.*?)</reasoning>", re.DOTALL | re.IGNORECASE)
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
        return None


# ---------------------------------------------------------------------------
# 3. StepWriter — now POSTs to API
# ---------------------------------------------------------------------------
class StepWriter:
    def write(self, record: dict) -> None:
        _post("/steps", record)


# ---------------------------------------------------------------------------
# 4. @episodic_trace  (unchanged internals, uses new StepWriter)
# ---------------------------------------------------------------------------
def episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
):
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = StepWriter()

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
                    writer.write(record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    import sys
                    print(f"[ageval] WARNING: step write failed: {write_exc}", file=sys.stderr)

        return wrapper
    return decorator


def async_episodic_trace(
    episode_id: str,
    step_index: int,
    llm_output: Optional[str] = None,
    swallow_write_errors: bool = True,
):
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name  = fn.__name__
            tool_input = {"args": list(args), "kwargs": kwargs}
            reasoning  = ReasoningExtractor.extract(llm_output)
            writer     = StepWriter()

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
                try:
                    writer.write(record)
                except Exception as write_exc:
                    if not swallow_write_errors:
                        raise
                    import sys
                    print(f"[ageval] WARNING: async step write failed: {write_exc}", file=sys.stderr)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 5. JobPusher — now POSTs to API
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
# 6. EpisodeSession  (unchanged, but start() now POSTs to API)
# ---------------------------------------------------------------------------
class EpisodeSession:
    def __init__(
        self,
        agent_id: str,
        task: str | None = None,
        swallow_write_errors: bool = True,
    ):
        self.episode_id           = new_episode_id()
        self.agent_id             = agent_id
        self.task                 = task
        self.swallow_write_errors = swallow_write_errors
        self._step_index          = 0
        self._langsmith_run_id    = None

    def start(self, langsmith_run_id: str | None = None):
        self._langsmith_run_id = langsmith_run_id or "pending"
        _post("/episodes", {
            "episode_id": self.episode_id,
            "agent_id"  : self.agent_id,
            "task"      : self.task,
        })
        return self

    def set_run_id(self, run_id: str):
        self._langsmith_run_id = run_id

    def trace(self, fn: Callable, reasoning: str | None = None) -> Callable:
        wrapped = episodic_trace(
            episode_id           = self.episode_id,
            step_index           = self._step_index,
            llm_output           = reasoning,
            swallow_write_errors = self.swallow_write_errors,
        )(fn)
        self._step_index += 1
        return wrapped

    def finish(self):
        return JobPusher().push(
            episode_id = self.episode_id,
            run_id     = self._langsmith_run_id or "none",
            agent_id   = self.agent_id,
            task       = self.task,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()
        return False


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