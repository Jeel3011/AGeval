"""
tests/test_sdk.py

Unit tests for sdk/episodic_sdk.py.
No network required — HTTP posts are monkeypatched.

Run with:
    pytest tests/test_sdk.py -v
"""

import pytest
from unittest.mock import patch

from sdk.episodic_sdk import (
    ErrorClassifier,
    ErrorCategory,
    ReasoningExtractor,
    episodic_trace,
    EpisodeSession,
    BatchStepWriter,
    _AtomicCounter,
    new_episode_id,
    _safe_serialize,
)


# ---------------------------------------------------------------------------
# Helper: capture what gets posted to the API
# ---------------------------------------------------------------------------
class _CapturingPost:
    """Replace _post with this to capture calls without network."""
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        return {"ok": True}


# ---------------------------------------------------------------------------
# new_episode_id
# ---------------------------------------------------------------------------
class TestNewEpisodeId:
    def test_format(self):
        eid = new_episode_id()
        assert eid.startswith("ep_")
        assert len(eid) == 3 + 16  # "ep_" + 16 hex chars

    def test_unique(self):
        ids = {new_episode_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# _safe_serialize
# ---------------------------------------------------------------------------
class TestSafeSerialize:
    def test_dict(self):
        assert _safe_serialize({"a": 1}) == {"a": 1}

    def test_string(self):
        assert _safe_serialize("hello") == "hello"

    def test_unserializable_falls_back_to_str(self):
        class Unserializable:
            def __repr__(self):
                return "MyObj()"
        v = _safe_serialize(Unserializable())
        assert isinstance(v, str)


# ---------------------------------------------------------------------------
# ErrorClassifier
# ---------------------------------------------------------------------------
class TestErrorClassifier:
    def test_connection_error_is_env(self):
        cat, rec = ErrorClassifier.classify(ConnectionError("refused"))
        assert cat == ErrorCategory.ENV_ERROR
        assert rec is True

    def test_value_error_is_agent(self):
        cat, rec = ErrorClassifier.classify(ValueError("bad value"))
        assert cat == ErrorCategory.AGENT_ERROR
        assert rec is False

    def test_timeout_in_message_is_env(self):
        cat, rec = ErrorClassifier.classify(Exception("request timed out"))
        assert cat == ErrorCategory.ENV_ERROR
        assert rec is True

    def test_unknown_exception(self):
        class WeirdError(Exception):
            pass
        cat, rec = ErrorClassifier.classify(WeirdError("something"))
        assert cat == ErrorCategory.UNKNOWN
        assert rec is True


# ---------------------------------------------------------------------------
# ReasoningExtractor
# ---------------------------------------------------------------------------
class TestReasoningExtractor:
    def test_xml_tag(self):
        text = "<reasoning>I need to search first</reasoning>"
        assert ReasoningExtractor.extract(text) == "I need to search first"

    def test_react_format(self):
        text = "Thought: I should look this up\nAction: search"
        result = ReasoningExtractor.extract(text)
        assert result is not None
        assert "look this up" in result

    def test_no_reasoning(self):
        assert ReasoningExtractor.extract("short") is None

    def test_none_input(self):
        assert ReasoningExtractor.extract(None) is None

    def test_empty_string(self):
        assert ReasoningExtractor.extract("") is None


# ---------------------------------------------------------------------------
# _AtomicCounter
# ---------------------------------------------------------------------------
class TestAtomicCounter:
    def test_sequential(self):
        c = _AtomicCounter()
        assert c.next() == 0
        assert c.next() == 1
        assert c.next() == 2

    def test_thread_safe(self):
        """Concurrent increments must produce unique values."""
        import threading
        c       = _AtomicCounter()
        results = []
        lock    = threading.Lock()

        def worker():
            for _ in range(100):
                v = c.next()
                with lock:
                    results.append(v)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000
        assert len(set(results)) == 1000  # all unique

    def test_start_value(self):
        c = _AtomicCounter(start=5)
        assert c.next() == 5


# ---------------------------------------------------------------------------
# @episodic_trace
# ---------------------------------------------------------------------------
class TestEpisodicTrace:
    def test_successful_call(self):
        cap = _CapturingPost()
        with patch("sdk.episodic_sdk._post", cap):
            @episodic_trace(episode_id="ep_test", step_index=0)
            def add(a, b):
                return a + b

            result = add(2, 3)

        assert result == 5
        assert len(cap.calls) == 1
        path, record = cap.calls[0]
        assert path == "/steps"
        assert record["success"] is True
        assert record["tool_name"] == "add"
        assert record["step_index"] == 0

    def test_failed_call_classified(self):
        cap = _CapturingPost()
        with patch("sdk.episodic_sdk._post", cap):
            @episodic_trace(episode_id="ep_test", step_index=1, swallow_write_errors=False)
            def bad_tool(x):
                raise ValueError("invalid input")

            with pytest.raises(ValueError):
                bad_tool("x")

        assert len(cap.calls) == 1
        _, record = cap.calls[0]
        assert record["success"] is False
        assert record["error_category"] == "agent_error"
        assert record["is_recoverable"] is False

    def test_reasoning_extracted(self):
        cap = _CapturingPost()
        with patch("sdk.episodic_sdk._post", cap):
            @episodic_trace(
                episode_id="ep_test",
                step_index=0,
                llm_output="<reasoning>Search for X first</reasoning>",
            )
            def search(q):
                return "results"

            search("query")

        _, record = cap.calls[0]
        assert record["reasoning"] == "Search for X first"

    def test_latency_recorded(self):
        cap = _CapturingPost()
        with patch("sdk.episodic_sdk._post", cap):
            @episodic_trace(episode_id="ep_test", step_index=0)
            def slow():
                import time
                time.sleep(0.01)
                return "done"

            slow()

        _, record = cap.calls[0]
        assert record["latency_ms"] >= 10  # at least 10ms

    def test_swallow_write_errors(self, capsys):
        """swallow_write_errors=True should print warning instead of raising."""
        def always_fail(path, payload):
            raise RuntimeError("db down")

        with patch("sdk.episodic_sdk._post", always_fail):
            @episodic_trace(episode_id="ep_test", step_index=0, swallow_write_errors=True)
            def ok_tool():
                return "fine"

            result = ok_tool()  # should NOT raise
        assert result == "fine"
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_no_swallow_write_errors(self):
        """swallow_write_errors=False should raise on write failure."""
        def always_fail(path, payload):
            raise RuntimeError("db down")

        with patch("sdk.episodic_sdk._post", always_fail):
            @episodic_trace(episode_id="ep_test", step_index=0, swallow_write_errors=False)
            def ok_tool():
                return "fine"

            with pytest.raises(RuntimeError, match="db down"):
                ok_tool()


# ---------------------------------------------------------------------------
# BatchStepWriter
# ---------------------------------------------------------------------------
class TestBatchStepWriter:
    def test_adds_and_flushes(self):
        writer    = BatchStepWriter()
        flushed   = []

        def fake_batch_post(path, payload):
            flushed.extend(payload)
            return {"ok": True}

        writer.add({"step_index": 0})
        writer.add({"step_index": 1})

        with patch("sdk.episodic_sdk._post_batch", fake_batch_post):
            writer.flush(swallow_errors=False)

        assert len(flushed) == 2
        assert flushed[0]["step_index"] == 0

    def test_flush_clears_buffer(self):
        writer  = BatchStepWriter()
        flushed = []

        def fake_batch_post(path, payload):
            flushed.extend(payload)
            return {}

        writer.add({"step_index": 0})
        with patch("sdk.episodic_sdk._post_batch", fake_batch_post):
            writer.flush()
            writer.flush()  # second flush — should post nothing

        assert len(flushed) == 1

    def test_empty_flush_is_noop(self):
        writer = BatchStepWriter()
        called = []

        def fake_batch_post(path, payload):
            called.append(payload)
            return {}

        with patch("sdk.episodic_sdk._post_batch", fake_batch_post):
            writer.flush()

        assert called == []


# ---------------------------------------------------------------------------
# EpisodeSession
# ---------------------------------------------------------------------------
class TestEpisodeSession:
    def test_session_lifecycle(self):
        posted = []

        def fake_post(path, payload):
            posted.append((path, payload))
            return {"ok": True, "episode_id": payload.get("episode_id", "ep_x")}

        with patch("sdk.episodic_sdk._post", fake_post):
            session = EpisodeSession(agent_id="test_agent", task="test task")
            session.start()

            @session.trace
            def my_tool(x):
                return x * 2

            result = my_tool(5)
            session.finish()

        assert result == 10
        paths = [p for p, _ in posted]
        assert "/episodes" in paths
        assert "/steps"    in paths
        assert "/jobs"     in paths

    def test_step_index_increments(self):
        posted = []

        def fake_post(path, payload):
            posted.append((path, payload))
            return {"ok": True, "episode_id": payload.get("episode_id", "ep_x")}

        with patch("sdk.episodic_sdk._post", fake_post):
            session = EpisodeSession(agent_id="test_agent")
            session.start()

            for _ in range(3):
                @session.trace
                def tool_fn():
                    return "result"
                tool_fn()

            session.finish()

        step_records = [p for path, p in posted if path == "/steps"]
        indices = [s["step_index"] for s in step_records]
        assert indices == [0, 1, 2]

    def test_batch_mode(self):
        posted         = []
        batch_posted   = []

        def fake_post(path, payload):
            posted.append((path, payload))
            return {"episode_id": payload.get("episode_id", "ep_x")}

        def fake_batch_post(path, payload):
            batch_posted.extend(payload)
            return {"ok": True}

        with patch("sdk.episodic_sdk._post",       fake_post), \
             patch("sdk.episodic_sdk._post_batch", fake_batch_post):
            session = EpisodeSession(agent_id="test_agent", batch=True)
            session.start()

            @session.trace
            def tool_a():
                return "a"

            @session.trace
            def tool_b():
                return "b"

            tool_a()
            tool_b()
            session.finish()

        # Individual /steps should NOT have been called
        step_paths = [p for p, _ in posted if p == "/steps"]
        assert len(step_paths) == 0

        # Batch should have received both steps
        assert len(batch_posted) == 2
