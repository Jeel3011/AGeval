"""
tests/test_session.py

Tests for the framework-agnostic AgentSession and related utilities.
Tests use mocking — no real API calls needed.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------
class TestClassifyError:
    def test_env_error_by_type(self):
        from ageval.session import classify_error

        exc = ConnectionError("connection refused")
        cat, recoverable = classify_error(exc)
        assert cat == "env_error"
        assert recoverable is True

    def test_agent_error_by_type(self):
        from ageval.session import classify_error

        exc = ValueError("invalid input")
        cat, recoverable = classify_error(exc)
        assert cat == "agent_error"
        assert recoverable is False

    def test_env_error_by_message(self):
        from ageval.session import classify_error

        exc = RuntimeError("request timed out after 30s")
        cat, recoverable = classify_error(exc)
        assert cat == "env_error"
        assert recoverable is True

    def test_agent_error_by_message(self):
        from ageval.session import classify_error

        exc = RuntimeError("missing field 'name' in config")
        cat, recoverable = classify_error(exc)
        assert cat == "agent_error"
        assert recoverable is False

    def test_unknown_error(self):
        from ageval.session import classify_error

        exc = RuntimeError("something unexpected happened")
        cat, recoverable = classify_error(exc)
        assert cat == "unknown"
        assert recoverable is True


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------
class TestAgentSession:
    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_session_lifecycle(self, mock_post):
        from ageval.session import AgentSession

        mock_post.return_value = {"ok": True}

        with AgentSession(agent_id="test_agent", task="unit test") as session:
            session.record_step(
                tool_name="search",
                tool_input={"query": "test"},
                tool_output={"results": ["a", "b"]},
                success=True,
                reasoning="testing",
                latency_ms=100,
            )
            session.record_step(
                tool_name="fetch",
                tool_input={"url": "http://example.com"},
                success=False,
                error_message="connection refused",
                error_category="env_error",
                latency_ms=5000,
            )

        assert session._step_counter == 2
        assert session._finished is True

        # Should have called: POST /episodes, POST /steps/batch, POST /jobs
        calls = [c[0][0] for c in mock_post.call_args_list]
        assert "/episodes" in calls
        # Batch flush happens on __exit__
        assert any("/steps/batch" in c for c in calls)

    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_record_error_classifies(self, mock_post):
        from ageval.session import AgentSession

        mock_post.return_value = {"ok": True}

        session = AgentSession(agent_id="test", batch=True)
        session.start()

        idx = session.record_error(
            tool_name="api_call",
            exc=ConnectionError("connection refused"),
            tool_input={"url": "http://example.com"},
        )

        assert idx == 0
        assert len(session._steps) == 1
        step = session._steps[0]
        assert step["success"] is False
        assert step["error_category"] == "env_error"
        assert step["is_recoverable"] is True

    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_traced_wrapper(self, mock_post):
        from ageval.session import AgentSession

        mock_post.return_value = {"ok": True}

        def my_tool(x: int) -> int:
            return x * 2

        session = AgentSession(agent_id="test", batch=True)
        session.start()

        traced_tool = session.traced(my_tool, reasoning="doubling input")
        result = traced_tool(5)

        assert result == 10
        assert len(session._steps) == 1
        assert session._steps[0]["tool_name"] == "my_tool"
        assert session._steps[0]["success"] is True
        assert session._steps[0]["reasoning"] == "doubling input"

    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_traced_wrapper_error(self, mock_post):
        from ageval.session import AgentSession

        mock_post.return_value = {"ok": True}

        def failing_tool():
            raise ValueError("bad input")

        session = AgentSession(agent_id="test", batch=True)
        session.start()

        traced = session.traced(failing_tool)
        with pytest.raises(ValueError, match="bad input"):
            traced()

        assert len(session._steps) == 1
        assert session._steps[0]["success"] is False
        assert session._steps[0]["error_category"] == "agent_error"

    @patch.dict("os.environ", {}, clear=False)
    def test_no_api_key_graceful(self):
        """Session should work without API key — just doesn't record."""
        from ageval.session import AgentSession

        # Remove AGEVAL_API_KEY if it exists
        import os
        old = os.environ.pop("AGEVAL_API_KEY", None)
        try:
            session = AgentSession(agent_id="test")
            session.start()
            session.record_step(tool_name="x", success=True)
            session.finish()
            assert session._step_counter == 1
        finally:
            if old:
                os.environ["AGEVAL_API_KEY"] = old

    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_thread_safety(self, mock_post):
        """Multiple threads can record_step concurrently."""
        from ageval.session import AgentSession

        mock_post.return_value = {"ok": True}

        session = AgentSession(agent_id="test", batch=True)
        session.start()

        def record_steps(n):
            for i in range(n):
                session.record_step(tool_name=f"tool_{threading.current_thread().name}", success=True)

        threads = [threading.Thread(target=record_steps, args=(10,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert session._step_counter == 50
        assert len(session._steps) == 50


# ---------------------------------------------------------------------------
# trace_callable
# ---------------------------------------------------------------------------
class TestTraceCallable:
    @patch.dict("os.environ", {"AGEVAL_API_KEY": "ageval-sk-test123"})
    @patch("ageval.session._post")
    def test_trace_callable_success(self, mock_post):
        from ageval.session import trace_callable

        mock_post.return_value = {"ok": True}

        def add(a, b):
            return a + b

        result = trace_callable(add, args=(3, 4), agent_id="calc", task="add numbers")
        assert result == 7

    @patch.dict("os.environ", {}, clear=False)
    def test_trace_callable_no_key(self):
        """Falls back to plain execution without API key."""
        from ageval.session import trace_callable

        import os
        old = os.environ.pop("AGEVAL_API_KEY", None)
        try:
            result = trace_callable(lambda x: x + 1, args=(5,), agent_id="test")
            assert result == 6
        finally:
            if old:
                os.environ["AGEVAL_API_KEY"] = old
