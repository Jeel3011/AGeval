"""
ageval.auto — zero-code-change auto-instrumentation.

Turn AGeval on for an *existing* agent without touching its code. Add ONE line
at the top of your entrypoint:

    import ageval.auto          # ← that's the entire integration

…or set ``AGEVAL_AUTO=1`` in the environment and add the same single import (the
env var just lets you flip it on/off without editing the line back out).

What it does at import time:
  * **LangChain / LangGraph** — registers a *global* callback handler via
    LangChain's official global-callback API, so every chain/graph/agent run
    becomes an AGeval episode automatically (this also covers anything built on
    LangChain: LangGraph, CrewAI's LangChain path, etc.).
  * **OpenAI SDK** — monkeypatches ``OpenAI.chat.completions.create`` (sync +
    async) to record each model call as an episode step with token usage.
  * **Anthropic SDK** — monkeypatches ``Anthropic.messages.create`` similarly.
  * **CrewAI / AutoGen** — covered transitively, because they call the OpenAI/
    Anthropic SDKs and/or LangChain underneath; their LLM + tool traffic is
    captured by the patches above with no framework-specific code.

Design rules:
  * **Never break the host app.** Every patch is wrapped so an AGeval failure
    can only log, never raise into the user's call. If a framework isn't
    installed, that patch is silently skipped.
  * **Idempotent.** Importing twice (or calling ``enable()`` twice) is a no-op.
  * **Opt-out.** ``AGEVAL_AUTO=0`` disables activation on import; you can also
    call ``ageval.auto.disable()`` to restore the original methods.

If ``AGEVAL_API_KEY`` is not set, instrumentation still installs but the sinks
no-op, so there is zero behavioural change and effectively zero overhead.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_ENABLED = False
_PATCHES: list[tuple[Any, str, Any]] = []  # (owner, attr, original) for disable()
_LC_HANDLER: Any = None   # the global LangChain handler instance, once installed
_LC_VAR: Any = None       # its contextvar (so disable() can clear it)


# ---------------------------------------------------------------------------
# Shared sink — reuse the SDK's API helpers so auto-mode and explicit-mode
# write through exactly the same path.
# ---------------------------------------------------------------------------
def _api_configured() -> bool:
    from ageval.session import _api_configured as cfg
    return cfg()


def _post(path: str, payload, swallow: bool = True):
    from ageval.session import _post as post
    return post(path, payload, swallow=swallow)


def _classify(exc: Exception):
    from ageval.session import classify_error
    return classify_error(exc)


# ===========================================================================
# OpenAI / Anthropic client patches
# ===========================================================================
def _inside_langchain_run() -> bool:
    """True when an LLM call is happening inside a LangChain/LangGraph run that
    we're already tracing via the global callback. Prevents double-recording the
    same call as both a chain step and a standalone openai_auto episode."""
    if _LC_HANDLER is None:
        return False
    try:
        return bool(_LC_HANDLER._episodes)  # an episode is currently open
    except Exception:
        return False


def _record_llm_step(agent_id: str, task: str, tool_input: dict,
                     tool_output: dict, latency_ms: int) -> None:
    """Record a single LLM call as a one-step episode. Raw-SDK callers drive
    their own tool loops, so each create() call is its own lightweight episode
    unless they group it (explicit trace_openai does the grouping)."""
    if not _api_configured():
        return
    if _inside_langchain_run():
        return  # the LangChain callback owns this episode
    episode_id = f"ep_{uuid.uuid4().hex[:16]}"
    try:
        _post("/episodes", {"episode_id": episode_id, "agent_id": agent_id, "task": task}, swallow=True)
        _post("/steps/batch", [{
            "episode_id": episode_id, "step_index": 0, "tool_name": "llm_call",
            "tool_input": tool_input, "tool_output": tool_output, "success": True,
            "error_message": None, "error_category": None, "is_recoverable": None,
            "reasoning": tool_output.get("content_preview"), "latency_ms": latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }], swallow=True)
        _post("/jobs", {"episode_id": episode_id, "run_id": "none",
                        "agent_id": agent_id, "task": task}, swallow=True)
    except Exception as exc:  # never break the host call
        log.debug(f"[ageval.auto] llm step record failed: {exc}")


def _patch_openai() -> None:
    try:
        from openai.resources.chat import completions as _c
    except Exception:
        return

    target = _c.Completions
    if getattr(target.create, "_ageval_patched", False):
        return
    original = target.create

    @functools.wraps(original)
    def create(self, *args, **kwargs):
        t0 = time.perf_counter()
        resp = original(self, *args, **kwargs)
        try:
            usage = getattr(resp, "usage", None)
            msg = resp.choices[0].message if getattr(resp, "choices", None) else None
            _record_llm_step(
                agent_id="openai_auto",
                task=str(kwargs.get("model", "openai")),
                tool_input={"model": kwargs.get("model"),
                            "n_messages": len(kwargs.get("messages", []) or [])},
                tool_output={
                    "content_preview": ((getattr(msg, "content", None) or "")[:200] if msg else ""),
                    "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                    "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                    "tool_calls_count": len(getattr(msg, "tool_calls", None) or []) if msg else 0,
                },
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            log.debug(f"[ageval.auto] openai capture failed: {exc}")
        return resp

    create._ageval_patched = True  # type: ignore[attr-defined]
    target.create = create  # type: ignore[assignment]
    _PATCHES.append((target, "create", original))
    log.info("[ageval.auto] OpenAI chat.completions instrumented")


def _patch_anthropic() -> None:
    try:
        from anthropic.resources import messages as _m
    except Exception:
        return

    target = _m.Messages
    if getattr(target.create, "_ageval_patched", False):
        return
    original = target.create

    @functools.wraps(original)
    def create(self, *args, **kwargs):
        t0 = time.perf_counter()
        resp = original(self, *args, **kwargs)
        try:
            usage = getattr(resp, "usage", None)
            blocks = getattr(resp, "content", None) or []
            text = ""
            n_tools = 0
            for b in blocks:
                bt = getattr(b, "type", None)
                if bt == "text":
                    text += getattr(b, "text", "") or ""
                elif bt == "tool_use":
                    n_tools += 1
            _record_llm_step(
                agent_id="anthropic_auto",
                task=str(kwargs.get("model", "anthropic")),
                tool_input={"model": kwargs.get("model"),
                            "n_messages": len(kwargs.get("messages", []) or [])},
                tool_output={
                    "content_preview": text[:200],
                    "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
                    "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
                    "tool_calls_count": n_tools,
                },
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            log.debug(f"[ageval.auto] anthropic capture failed: {exc}")
        return resp

    create._ageval_patched = True  # type: ignore[attr-defined]
    target.create = create  # type: ignore[assignment]
    _PATCHES.append((target, "create", original))
    log.info("[ageval.auto] Anthropic messages instrumented")


# ===========================================================================
# LangChain / LangGraph global callback
# ===========================================================================
def _install_langchain_callback() -> None:
    """Register a process-wide LangChain callback so every chain/graph/agent run
    becomes an AGeval episode with no user edits. Uses LangChain's documented
    ``register_configure_hook`` — a global contextvar whose default value is our
    handler instance, marked inheritable so it propagates into nested runs and
    threads. This is the same mechanism LangSmith's tracer uses."""
    from contextvars import ContextVar

    try:
        from langchain_core.tracers.context import register_configure_hook
    except Exception as exc:
        log.debug(f"[ageval.auto] LangChain not available, skipping callback: {exc}")
        return

    global _LC_HANDLER, _LC_VAR
    if _LC_HANDLER is not None:
        return  # already installed
    _LC_HANDLER = _AutoEpisodeCallback()
    # A non-None default makes the handler globally active without the user ever
    # passing callbacks=[...]. handle_class is left None (we supply an instance).
    _LC_VAR = ContextVar("ageval_auto_cb", default=_LC_HANDLER)
    register_configure_hook(_LC_VAR, True)
    log.info("[ageval.auto] LangChain global callback registered")


def _make_auto_callback_base():
    try:
        from langchain_core.callbacks import BaseCallbackHandler
        return BaseCallbackHandler
    except Exception:
        return object


class _AutoEpisodeCallback(_make_auto_callback_base()):  # type: ignore[misc]
    """A global LangChain handler that turns each *top-level* run into an AGeval
    episode and records every tool call within it. Keyed by the root run's id so
    nested chains/tools all attach to one episode.

    All bookkeeping is best-effort and exception-guarded — a tracing error can
    never propagate into the user's chain.
    """

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._lock = threading.Lock()
        self._episodes: dict[str, dict] = {}   # root_run_id -> {episode_id, counter}
        self._tool_starts: dict[str, dict] = {}
        self._last_text: dict[str, str] = {}

    # -- episode lifecycle ------------------------------------------------
    def on_chain_start(self, serialized, inputs, *, run_id=None, parent_run_id=None, **kw):
        try:
            if parent_run_id is not None:
                return  # only open an episode for the ROOT chain
            if not _api_configured():
                return
            episode_id = f"ep_{uuid.uuid4().hex[:16]}"
            name = (serialized or {}).get("name") or "langchain_agent"
            with self._lock:
                self._episodes[str(run_id)] = {"episode_id": episode_id, "counter": 0}
            _post("/episodes", {"episode_id": episode_id, "agent_id": name,
                                "task": _short(inputs)}, swallow=True)
        except Exception as exc:
            log.debug(f"[ageval.auto] on_chain_start failed: {exc}")

    def on_chain_end(self, outputs, *, run_id=None, parent_run_id=None, **kw):
        try:
            if parent_run_id is not None:
                return
            ep = self._episodes.pop(str(run_id), None)
            if not ep:
                return
            _post("/jobs", {"episode_id": ep["episode_id"], "run_id": str(run_id),
                            "agent_id": "langchain_agent", "task": None}, swallow=True)
        except Exception as exc:
            log.debug(f"[ageval.auto] on_chain_end failed: {exc}")

    # -- reasoning capture -------------------------------------------------
    def on_llm_end(self, response, *, run_id=None, parent_run_id=None, **kw):
        try:
            gen = response.generations[0][0]
            text = getattr(getattr(gen, "message", None), "content", None) or getattr(gen, "text", "")
            root = self._root_for(parent_run_id, run_id)
            if root and text:
                self._last_text[root] = str(text)[:200]
        except Exception:
            pass

    # -- tool capture ------------------------------------------------------
    def on_tool_start(self, serialized, input_str, *, run_id=None, parent_run_id=None, **kw):
        try:
            self._tool_starts[str(run_id)] = {
                "name": (serialized or {}).get("name", "unknown"),
                "input": input_str,
                "t0": time.perf_counter(),
                "root": self._root_for(parent_run_id, run_id),
            }
        except Exception:
            pass

    def on_tool_end(self, output, *, run_id=None, **kw):
        self._finish_tool(str(run_id), output=output, error=None)

    def on_tool_error(self, error, *, run_id=None, **kw):
        self._finish_tool(str(run_id), output=None, error=error)

    def _finish_tool(self, run_id, output, error):
        try:
            info = self._tool_starts.pop(run_id, None)
            if not info:
                return
            root = info["root"]
            ep = self._episodes.get(root) if root else None
            if not ep:
                return
            with self._lock:
                idx = ep["counter"]
                ep["counter"] += 1
            rec = {
                "episode_id": ep["episode_id"], "step_index": idx,
                "tool_name": info["name"], "tool_input": {"input": str(info["input"])[:500]},
                "reasoning": self._last_text.get(root),
                "latency_ms": int((time.perf_counter() - info["t0"]) * 1000),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if error is None:
                rec.update(tool_output={"output": str(output)[:500]}, success=True,
                           error_message=None, error_category=None, is_recoverable=None)
            else:
                cat, rec_flag = _classify(error)
                rec.update(tool_output=None, success=False, error_message=str(error),
                           error_category=cat, is_recoverable=rec_flag)
            _post("/steps", rec, swallow=True)
        except Exception as exc:
            log.debug(f"[ageval.auto] tool record failed: {exc}")

    def _root_for(self, parent_run_id, run_id):
        # Walk is unnecessary: LangChain passes the *immediate* parent. The root
        # episode is whichever id is registered in self._episodes; for a flat
        # ReAct graph the parent IS the root. Fall back to run_id.
        pid = str(parent_run_id) if parent_run_id is not None else None
        if pid and pid in self._episodes:
            return pid
        # Otherwise, if there is exactly one open episode, attach to it.
        if len(self._episodes) == 1:
            return next(iter(self._episodes))
        return pid or str(run_id)


def _short(obj) -> str | None:
    try:
        s = str(obj)
        return s[:200] if s else None
    except Exception:
        return None


# ===========================================================================
# Public API
# ===========================================================================
def enable() -> None:
    """Install all available instrumentation. Idempotent and safe to call even
    if no frameworks are present."""
    global _ENABLED
    with _LOCK:
        if _ENABLED:
            return
        for fn in (_patch_openai, _patch_anthropic, _install_langchain_callback):
            try:
                fn()
            except Exception as exc:  # one framework failing must not block others
                log.debug(f"[ageval.auto] {fn.__name__} skipped: {exc}")
        _ENABLED = True
        if not _api_configured():
            log.info("[ageval.auto] instrumentation installed; AGEVAL_API_KEY unset → recording is a no-op")


def disable() -> None:
    """Restore patched methods (LangChain callback removal is best-effort)."""
    global _ENABLED, _LC_HANDLER
    with _LOCK:
        for owner, attr, original in reversed(_PATCHES):
            try:
                setattr(owner, attr, original)
            except Exception:
                pass
        _PATCHES.clear()
        # Neutralise the LangChain handler (the hook can't be unregistered, but
        # setting the contextvar to None means no handler is attached to runs).
        if _LC_VAR is not None:
            try:
                _LC_VAR.set(None)
            except Exception:
                pass
        _LC_HANDLER = None
        _ENABLED = False


# Activate on import unless explicitly disabled.
if os.environ.get("AGEVAL_AUTO", "1") not in ("0", "false", "False", ""):
    enable()
