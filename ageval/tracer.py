"""
ageval/tracer.py

The single entry point for any agent to plug into the eval pipeline.

User writes ONE line in their code:

    from ageval import trace_agent
    result = trace_agent(agent=react_app, input=messages, agent_id="my_agent", task="do X")

Everything else is automatic.

Fixes applied:
  - _EpisodicCallback is now a proper class (no dynamic __class__ reassignment)
  - run_id is captured from langsmith.get_current_run_tree() inside the trace,
    not from list_runs (which returns the wrong run under concurrency)
  - Job push uses a non-daemon thread so it survives short-lived processes
  - _step_index is protected by threading.Lock (safe for parallel tool calls)
  - ageval_package now POSTs to the ingestion API (same path as the SDK),
    no direct Supabase writes. Only AGEVAL_API_KEY is needed.
  - user_id is extracted from the API key and threaded through all writes
"""

from __future__ import annotations

import os
import re
import time
import uuid
import json
import logging
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared error/reasoning helpers (single canonical copy)
# ---------------------------------------------------------------------------

_ENV_ERRORS   = {"ConnectionError","Timeout","ReadTimeout","ConnectTimeout",
                  "HTTPError","RequestException","RateLimitError","OSError",
                  "IOError","TimeoutError","ServiceUnavailableError"}
_AGENT_ERRORS = {"ValueError","TypeError","KeyError","AttributeError",
                  "AssertionError","NotImplementedError","JSONDecodeError","ValidationError"}


def _classify_error(exc: Exception) -> tuple[str, bool]:
    name = type(exc).__name__
    msg  = str(exc).lower()
    if name in _ENV_ERRORS:
        return "env_error", True
    if name in _AGENT_ERRORS:
        return "agent_error", False
    # message-based fallback
    env_patterns   = [r"timeout", r"connection (refused|reset)", r"rate limit",
                       r"429", r"503", r"502", r"ssl", r"dns"]
    agent_patterns = [r"invalid (argument|parameter|input)", r"missing (field|key)",
                       r"cannot parse", r"failed to decode"]
    for p in env_patterns:
        if re.search(p, msg, re.IGNORECASE):
            return "env_error", True
    for p in agent_patterns:
        if re.search(p, msg, re.IGNORECASE):
            return "agent_error", False
    return "unknown", True


def _extract_reasoning(text: str | None) -> str | None:
    """
    Extract reasoning/chain-of-thought from LLM output.
    Supports 3 formats (synced with sdk/episodic_sdk.py ReasoningExtractor):
      1. XML tags: <reasoning>...</reasoning> or <thinking>...</thinking>
      2. ReAct: Thought: / Reasoning: / Think:
      3. OpenAI: content before a tool-call block
    """
    if not text or not text.strip():
        return None
    # 1. XML/tag format (<reasoning> or <thinking>)
    m = re.search(
        r"<(?:reasoning|thinking)[^>]*>(.*?)</(?:reasoning|thinking)>",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip() or None
    # 2. ReAct format (Thought: / Think: / Reasoning:)
    m = re.search(
        r"^(?:thought|reasoning|think)[:\s]+(.+?)(?=\n(?:action|tool|observation)|$)",
        text, re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if m:
        extracted = m.group(1).strip()
        return extracted or None
    # 3. OpenAI content before tool call block
    m = re.search(
        r'^(.+?)(?=\n(?:```|\{\s*\"type\"\s*:|function_call|tool_call))',
        text, re.DOTALL,
    )
    if m:
        candidate = m.group(1).strip()
        if len(candidate) > 20 and not candidate.startswith("{"):
            return candidate
    return None


# ---------------------------------------------------------------------------
# API client helpers (use same API as sdk/episodic_sdk.py)
# ---------------------------------------------------------------------------

def _get_api_base() -> str:
    return os.environ.get("AGEVAL_API_URL", "https://ageval-production.up.railway.app").rstrip("/")


def _get_api_key() -> str:
    k = os.environ.get("AGEVAL_API_KEY", "")
    if not k:
        raise RuntimeError("AGEVAL_API_KEY not set")
    return k


def _api_post(path: str, payload: dict, swallow: bool = True) -> dict | None:
    """POST to the ageval ingestion API. Returns response dict or None on error."""
    try:
        url  = f"{_get_api_base()}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={
                "Content-Type" : "application/json",
                "Authorization": f"Bearer {_get_api_key()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        if swallow:
            log.warning(f"[ageval] API post to {path} failed: {exc}")
            return None
        raise


def _api_get(path: str, swallow: bool = True) -> dict | None:
    """GET from the ageval ingestion API."""
    try:
        url = f"{_get_api_base()}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {_get_api_key()}",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        if swallow:
            log.warning(f"[ageval] API get to {path} failed: {exc}")
            return None
        raise


def _api_configured() -> bool:
    return bool(os.environ.get("AGEVAL_API_KEY"))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def recall_episodes(task: str, k: int = 3) -> list[dict]:
    """Retrieve past episodes relevant to the given task."""
    if not _api_configured():
        log.warning("[ageval] AGEVAL_API_KEY not set - running without API")
        return []
    qs = urllib.parse.urlencode({"task": task, "k": k})
    resp = _api_get(f"/recall?{qs}", swallow=False)
    if resp and "episodes" in resp:
        return resp["episodes"]
    return []

def compare_episodes(episode_a: str, episode_b: str) -> dict:
    """Compare two past episodes to see differences."""
    if not _api_configured():
        return {}
    qs = urllib.parse.urlencode({"episode_a": episode_a, "episode_b": episode_b})
    resp = _api_get(f"/compare?{qs}", swallow=False)
    return resp or {}


def trace_agent(
    agent,
    input       : dict,
    agent_id    : str,
    task        : str | None = None,
    config      : dict | None = None,
) -> Any:
    """
    Wrap any LangGraph/LangChain agent invoke() call with full episodic tracing.

    Args:
        agent    : your compiled LangGraph app (result of graph.compile())
        input    : the dict you'd normally pass to agent.invoke()
        agent_id : a stable name for your agent e.g. "trip_planner_v1"
        task     : human-readable description of what this run is doing
        config   : any extra LangGraph config you were already passing

    Returns:
        Whatever your agent.invoke() normally returns — unchanged.

    Side effects (fully automatic, in background thread):
        - Creates episode row via ageval API
        - Attaches callback that captures every tool call
        - Pushes job to episode_jobs queue after run completes
        - Merger worker picks it up and scores it

    Requirements (env vars):
        AGEVAL_API_KEY  — your ageval API key (all you need)
    """

    if not _api_configured():
        log.warning("[ageval] AGEVAL_API_KEY not set — running without tracing")
        return agent.invoke(input, config=config or {})

    episode_id = f"ep_{uuid.uuid4().hex[:16]}"

    # Insert stub episode row
    resp = _api_post("/episodes", {
        "episode_id": episode_id,
        "agent_id"  : agent_id,
        "task"      : task,
    }, swallow=False)

    if resp is None:
        log.warning("[ageval] Failed to create episode — running without tracing")
        return agent.invoke(input, config=config or {})

    # Build callback and attach to config
    callback      = _EpisodicCallback(episode_id=episode_id)
    merged_config = dict(config or {})
    existing_cbs  = merged_config.get("callbacks", [])
    merged_config["callbacks"] = [*existing_cbs, callback]

    # Run the agent; run_id is captured inside on_chain_end
    run_result = agent.invoke(input, config=merged_config)

    # Push job to queue in a NON-daemon thread so it survives short-lived processes
    t = threading.Thread(
        target = _push_job_sync,
        args   = (episode_id, callback.captured_run_id, agent_id, task),
        daemon = False,     # ← critical: daemon=False means the process won't exit
    )                       #   until this thread finishes (max ~15s including sleep)
    t.start()

    return run_result


# ---------------------------------------------------------------------------
# Internal: push job (runs in background thread)
# ---------------------------------------------------------------------------

def _push_job_sync(
    episode_id    : str,
    captured_run_id: str | None,
    agent_id      : str,
    task          : str | None,
) -> None:
    """
    Wait briefly for LangSmith ingestion, then push the episode job.
    Runs in a non-daemon thread — blocking is intentional.
    """
    import time as _time

    run_id = captured_run_id

    if not run_id:
        # Give LangSmith up to 10s to ingest before giving up
        _time.sleep(5)
        run_id = _fetch_langsmith_run_id_for_episode()

    run_id = run_id or "unknown"

    _api_post("/jobs", {
        "episode_id": episode_id,
        "run_id"    : run_id,
        "agent_id"  : agent_id,
        "task"      : task,
    }, swallow=True)

    log.info(f"[ageval] Job pushed: episode={episode_id} run={run_id}")


def _fetch_langsmith_run_id_for_episode() -> str | None:
    """
    Last-resort fallback: try get_current_run_tree() which is likely
    still in scope from the invoke() call above.
    """
    try:
        import langsmith
        ctx = langsmith.get_current_run_tree()
        if ctx:
            return str(ctx.id)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Internal: LangChain callback (proper inheritance, no __class__ hack)
# ---------------------------------------------------------------------------

try:
    from langchain_core.callbacks import BaseCallbackHandler as _BaseHandler
    _HAS_LANGCHAIN = True
except ImportError:
    _HAS_LANGCHAIN = False
    _BaseHandler   = object  # fallback so the class definition below still works


class _EpisodicCallback(_BaseHandler):  # type: ignore[misc]
    """
    LangChain BaseCallbackHandler that intercepts every tool call.
    Internal to ageval — users never see or touch this class.

    Inherits from BaseCallbackHandler at class definition time (not at
    instance creation), so there is no dynamic __class__ reassignment.
    """

    def __init__(self, episode_id: str):
        if _HAS_LANGCHAIN:
            super().__init__()

        self.episode_id      = episode_id
        self.captured_run_id : str | None = None    # set in on_chain_end
        self._lock           = threading.Lock()
        self._step_counter   = 0
        self._tool_starts    : dict[str, dict] = {}
        self._last_llm       : str | None = None

    def _next_step(self) -> int:
        with self._lock:
            idx = self._step_counter
            self._step_counter += 1
            return idx

    # ── LangChain hooks ─────────────────────────────────────────────────

    def on_chain_end(self, outputs, *, run_id=None, **kwargs):
        """Capture the top-level run_id from the chain/graph that just finished."""
        try:
            import langsmith
            ctx = langsmith.get_current_run_tree()
            if ctx and self.captured_run_id is None:
                self.captured_run_id = str(ctx.id)
        except Exception:
            pass

    def on_llm_end(self, response, **kwargs):
        try:
            self._last_llm = response.generations[0][0].text
        except Exception:
            self._last_llm = None

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._tool_starts[str(run_id)] = {
            "name"      : serialized.get("name", "unknown"),
            "input"     : input_str,
            "start_time": time.perf_counter(),
            "reasoning" : _extract_reasoning(self._last_llm),
        }

    def on_tool_end(self, output, *, run_id, **kwargs):
        info = self._tool_starts.pop(str(run_id), None)
        if not info:
            return
        self._write(
            tool_name      = info["name"],
            tool_input     = {"input": info["input"]},
            tool_output    = {"output": str(output)},
            success        = True,
            error_message  = None,
            error_category = None,
            is_recoverable = None,
            reasoning      = info["reasoning"],
            latency_ms     = int((time.perf_counter() - info["start_time"]) * 1000),
        )

    def on_tool_error(self, error, *, run_id, **kwargs):
        info = self._tool_starts.pop(str(run_id), None)
        if not info:
            return
        cat, rec = _classify_error(error)
        self._write(
            tool_name      = info["name"],
            tool_input     = {"input": info["input"]},
            tool_output    = None,
            success        = False,
            error_message  = str(error),
            error_category = cat,
            is_recoverable = rec,
            reasoning      = info["reasoning"],
            latency_ms     = int((time.perf_counter() - info["start_time"]) * 1000),
        )

    def _write(self, **fields) -> None:
        record = {
            "episode_id": self.episode_id,
            "step_index": self._next_step(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        _api_post("/steps", record, swallow=True)
