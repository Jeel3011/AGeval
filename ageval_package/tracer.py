"""
ageval/tracer.py

The single entry point for any agent to plug into the eval pipeline.

User writes ONE line in their code:

    from ageval import trace_agent
    result = trace_agent(agent=react_app, input=messages, agent_id="my_agent", task="do X")

Everything else is automatic.
"""

from __future__ import annotations

import os
import uuid
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


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
        - Creates episode row in AGeval Supabase
        - Attaches callback that captures every tool call
        - Pushes job to episode_jobs queue after run completes
        - Merger worker picks it up and scores it

    Requirements (env vars):
        AGEVAL_SUPABASE_URL         - your AGeval project URL
        AGEVAL_SUPABASE_SERVICE_KEY - service role key (not anon)
        LANGSMITH_API_KEY           - for fetching trace
        LANGSMITH_PROJECT           - LangSmith project name
    """

    client = _get_client()
    if client is None:
        # AGeval not configured — run agent normally, skip tracing
        log.warning("[ageval] AGEVAL_SUPABASE_URL/KEY not set — running without tracing")
        merged_config = config or {}
        return agent.invoke(input, config=merged_config)

    episode_id = f"ep_{uuid.uuid4().hex[:16]}"

    # Insert stub episodes row (FK required before steps can write)
    try:
        client.table("episodes").insert({
            "episode_id": episode_id,
            "agent_id"  : agent_id,
            "run_id"    : "pending",
            "task"      : task,
        }).execute()
    except Exception as e:
        log.warning(f"[ageval] Failed to create episode row: {e} — running without tracing")
        merged_config = config or {}
        return agent.invoke(input, config=merged_config)

    # Build callback and attach to config
    callback     = _EpisodicCallback(episode_id=episode_id, client=client)
    merged_config = dict(config or {})
    existing_cbs  = merged_config.get("callbacks", [])
    merged_config["callbacks"] = [*existing_cbs, callback]

    # Run the agent
    result = agent.invoke(input, config=merged_config)

    # Push job to queue in background — don't slow down the response
    threading.Thread(
        target=_push_job_async,
        args=(client, episode_id, agent_id, task),
        daemon=True,
    ).start()

    return result


# ---------------------------------------------------------------------------
# Internal: Supabase client
# ---------------------------------------------------------------------------
def _get_client():
    url = os.environ.get("AGEVAL_SUPABASE_URL")
    key = os.environ.get("AGEVAL_SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        log.warning("[ageval] supabase-py not installed. Run: pip install supabase")
        return None
    except Exception as e:
        log.warning(f"[ageval] Supabase client init failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Internal: push job to queue (runs in background thread)
# ---------------------------------------------------------------------------
def _push_job_async(client, episode_id, agent_id, task):
    """
    Fetches the LangSmith run_id and pushes episode_jobs row.
    Runs in a daemon thread so it doesn't block the HTTP response.
    """
    import time as _time
    _time.sleep(3)  # give LangSmith time to ingest the run

    run_id = _fetch_langsmith_run_id()

    try:
        client.table("episodes").update(
            {"run_id": run_id}
        ).eq("episode_id", episode_id).execute()

        client.table("episode_jobs").insert({
            "episode_id" : episode_id,
            "run_id"     : run_id,
            "agent_id"   : agent_id,
            "task"       : task,
            "status"     : "pending",
            "retry_count": 0,
            "created_at" : datetime.now(timezone.utc).isoformat(),
        }).execute()

        log.info(f"[ageval] Job pushed: episode={episode_id} run={run_id}")
    except Exception as e:
        log.warning(f"[ageval] Failed to push job: {e}")


def _fetch_langsmith_run_id() -> str:
    try:
        from langsmith import Client as LSClient
        ls   = LSClient(api_key=os.environ.get("LANGSMITH_API_KEY"))
        runs = list(ls.list_runs(
            project_name=os.environ.get("LANGSMITH_PROJECT", "default"),
            limit=1,
        ))
        if runs:
            return str(runs[0].id)
    except Exception as e:
        log.warning(f"[ageval] Could not fetch LangSmith run_id: {e}")
    return "unknown"


# ---------------------------------------------------------------------------
# Internal: LangChain callback
# ---------------------------------------------------------------------------
class _EpisodicCallback:
    """
    LangChain BaseCallbackHandler that intercepts every tool call.
    Internal to ageval — users never see or touch this class.
    """

    def __init__(self, episode_id: str, client):
        self.episode_id   = episode_id
        self.client       = client
        self._step_index  = 0
        self._tool_starts = {}
        self._last_llm    = None

        # Dynamically inherit from BaseCallbackHandler if langchain is available
        try:
            from langchain_core.callbacks import BaseCallbackHandler
            self.__class__ = type(
                "_EpisodicCallback",
                (BaseCallbackHandler,),
                dict(self.__class__.__dict__),
            )
            BaseCallbackHandler.__init__(self)
        except ImportError:
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
            tool_name=info["name"],
            tool_input={"input": info["input"]},
            tool_output={"output": str(output)},
            success=True,
            error_message=None,
            error_category=None,
            is_recoverable=None,
            reasoning=info["reasoning"],
            latency_ms=int((time.perf_counter() - info["start_time"]) * 1000),
        )

    def on_tool_error(self, error, *, run_id, **kwargs):
        info = self._tool_starts.pop(str(run_id), None)
        if not info:
            return
        cat, rec = _classify_error(error)
        self._write(
            tool_name=info["name"],
            tool_input={"input": info["input"]},
            tool_output=None,
            success=False,
            error_message=str(error),
            error_category=cat,
            is_recoverable=rec,
            reasoning=info["reasoning"],
            latency_ms=int((time.perf_counter() - info["start_time"]) * 1000),
        )

    def _write(self, **fields):
        record = {
            "episode_id": self.episode_id,
            "step_index": self._step_index,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self._step_index += 1
        try:
            self.client.table("episode_steps").insert(record).execute()
        except Exception as e:
            log.warning(f"[ageval] step write failed: {e}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _extract_reasoning(text: str | None) -> str | None:
    if not text:
        return None
    import re
    m = re.search(r"<reasoning[^>]*>(.*?)</reasoning>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"^(?:thought|reasoning|think)[:\s]+(.+?)(?=\n(?:action|tool|observation)|$)",
        text, re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if m:
        return m.group(1).strip()
    return None


def _classify_error(exc: Exception) -> tuple[str, bool]:
    env   = {"ConnectionError","Timeout","ReadTimeout","HTTPError",
             "RateLimitError","OSError","IOError","TimeoutError"}
    agent = {"ValueError","TypeError","KeyError","AttributeError",
             "JSONDecodeError","ValidationError"}
    name  = type(exc).__name__
    if name in env:
        return "env_error", True
    if name in agent:
        return "agent_error", False
    return "unknown", True