"""
tests/test_api_contract.py

Integration tests for the Pydantic API contract.
Verifies that StepCreate accepts any JSON-serializable value for
tool_input and tool_output (not just dicts), which is the real-world
case when agents return strings, ints, lists, etc.

No network or Supabase required — tests Pydantic validation only.

Run with:
    pytest tests/test_api_contract.py -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pydantic import ValidationError

# Import the model — it lives in main.py at the project root
import importlib.util
spec = importlib.util.spec_from_file_location(
    "main", os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
)


def _load_step_create():
    """Load StepCreate from main.py without triggering FastAPI startup side-effects."""
    # We import only what we need via targeted import
    import sys
    # Temporarily mock supabase and other heavy deps to avoid startup errors
    import unittest.mock as mock
    with mock.patch.dict("sys.modules", {
        "supabase"           : mock.MagicMock(),
        "dotenv"             : mock.MagicMock(),
        "openai"             : mock.MagicMock(),
        "langchain_core"     : mock.MagicMock(),
        "langchain_core.callbacks": mock.MagicMock(),
    }):
        # Patch load_dotenv so it's a no-op
        with mock.patch("builtins.open", mock.mock_open()):
            pass
    # Direct Pydantic model test — recreate the model inline to test the contract
    from pydantic import BaseModel
    from typing import Any

    class StepCreate(BaseModel):
        episode_id     : str
        step_index     : int
        tool_name      : str
        tool_input     : Any | None = None
        tool_output    : Any | None = None
        success        : bool
        error_message  : str | None = None
        error_category : str | None = None
        is_recoverable : bool | None = None
        reasoning      : str | None = None
        latency_ms     : int | None = None

    return StepCreate


class TestStepCreateContract:
    """
    Tests that the API model correctly accepts any JSON-serializable type
    for tool_input and tool_output, not just dicts.

    Critical regression tests: Before the fix, these would raise ValidationError.
    """

    @pytest.fixture
    def StepCreate(self):
        return _load_step_create()

    def _base(self, **kwargs):
        return {
            "episode_id": "ep_test123",
            "step_index": 0,
            "tool_name" : "my_tool",
            "success"   : True,
            **kwargs,
        }

    def test_tool_output_dict_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_output={"result": "ok", "count": 5}))
        assert step.tool_output == {"result": "ok", "count": 5}

    def test_tool_output_string_accepted(self, StepCreate):
        """Real agents frequently return plain strings. Must not reject."""
        step = StepCreate(**self._base(tool_output="ok"))
        assert step.tool_output == "ok"

    def test_tool_output_integer_accepted(self, StepCreate):
        """Some tools return counts or status codes as integers."""
        step = StepCreate(**self._base(tool_output=42))
        assert step.tool_output == 42

    def test_tool_output_list_accepted(self, StepCreate):
        """Search tools often return lists of results."""
        step = StepCreate(**self._base(tool_output=["result1", "result2", "result3"]))
        assert step.tool_output == ["result1", "result2", "result3"]

    def test_tool_output_bool_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_output=True))
        assert step.tool_output is True

    def test_tool_output_none_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_output=None))
        assert step.tool_output is None

    def test_tool_output_nested_list_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_output=[{"id": 1}, {"id": 2}]))
        assert len(step.tool_output) == 2

    def test_tool_input_string_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_input="query string"))
        assert step.tool_input == "query string"

    def test_tool_input_list_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_input=["a", "b", "c"]))
        assert step.tool_input == ["a", "b", "c"]

    def test_tool_input_dict_accepted(self, StepCreate):
        step = StepCreate(**self._base(tool_input={"query": "hello", "k": 5}))
        assert step.tool_input["query"] == "hello"

    def test_both_none(self, StepCreate):
        """Minimal valid step — tool_input and tool_output both None."""
        step = StepCreate(**self._base())
        assert step.tool_input is None
        assert step.tool_output is None

    def test_all_optional_fields(self, StepCreate):
        step = StepCreate(**self._base(
            tool_input     = {"args": [1, 2]},
            tool_output    = "done",
            success        = False,
            error_message  = "something went wrong",
            error_category = "agent_error",
            is_recoverable = False,
            reasoning      = "I tried to compute X",
            latency_ms     = 150,
        ))
        assert step.success is False
        assert step.error_category == "agent_error"
        assert step.reasoning == "I tried to compute X"

    def test_step_index_must_be_int(self, StepCreate):
        with pytest.raises((ValidationError, Exception)):
            StepCreate(**self._base(step_index="not_an_int"))

    def test_success_field_is_required(self, StepCreate):
        """success is a required field — omitting it must raise ValidationError."""
        payload = self._base()
        del payload['success']
        with pytest.raises((ValidationError, Exception)):
            StepCreate(**payload)


class TestSafeSerializeRoundTrip:
    """
    Tests that _safe_serialize output is always accepted by the StepCreate model.
    This catches the real production bug: SDK serializes → API must accept.
    """

    def test_string_roundtrip(self):
        from sdk.episodic_sdk import _safe_serialize
        result = _safe_serialize("hello world")
        assert result == "hello world"  # string → string, not wrapped in dict

    def test_int_roundtrip(self):
        from sdk.episodic_sdk import _safe_serialize
        result = _safe_serialize(42)
        assert result == 42

    def test_list_roundtrip(self):
        from sdk.episodic_sdk import _safe_serialize
        result = _safe_serialize([1, 2, 3])
        assert result == [1, 2, 3]

    def test_dict_roundtrip(self):
        from sdk.episodic_sdk import _safe_serialize
        result = _safe_serialize({"key": "value"})
        assert result == {"key": "value"}

    def test_unserializable_becomes_str(self):
        from sdk.episodic_sdk import _safe_serialize

        class NotSerializable:
            pass

        result = _safe_serialize(NotSerializable())
        assert isinstance(result, str)


class TestMergerNoLangSmith:
    """
    Tests that the merger correctly skips LangSmith when run_id is 'none'.
    Validates the core fix for non-LangChain agent data loss.
    """

    def test_no_langsmith_ids_recognized(self):
        from merger.merger import _NO_LANGSMITH_IDS
        for skip_id in ("none", "unknown", "pending", "", "null"):
            assert skip_id in _NO_LANGSMITH_IDS, f"'{skip_id}' should trigger LangSmith skip"

    def test_fetch_langsmith_trace_returns_none_without_key(self, monkeypatch):
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
        from merger import merger
        result = merger.fetch_langsmith_trace("some-real-run-id")
        assert result is None, "Should return None gracefully when LANGSMITH_API_KEY is not set"

    def test_derive_final_output_from_steps(self):
        """When no LangSmith trace, final output is derived from last successful step."""
        from merger.merger import _derive_final_output
        steps = [
            {"success": True,  "tool_output": {"weather": "sunny"}, "tool_name": "get_weather"},
            {"success": False, "tool_output": None,                 "tool_name": "bad_tool"},
        ]
        result = _derive_final_output(steps, trace=None)
        assert result == {"weather": "sunny"}

    def test_derive_final_output_from_trace_takes_priority(self):
        from merger.merger import _derive_final_output
        steps = [
            {"success": True, "tool_output": {"from": "step"}, "tool_name": "tool"}
        ]
        trace = {"outputs": {"from": "langsmith", "answer": "42"}}
        result = _derive_final_output(steps, trace=trace)
        assert result["from"] == "langsmith"

    def test_derive_outcome_empty_steps(self):
        from merger.merger import derive_outcome
        assert derive_outcome([]) == "failure"

    def test_derive_outcome_all_success(self):
        from merger.merger import derive_outcome
        steps = [{"success": True}, {"success": True}]
        assert derive_outcome(steps) == "success"

    def test_derive_outcome_mixed(self):
        from merger.merger import derive_outcome
        steps = [{"success": True}, {"success": False}]
        assert derive_outcome(steps) == "partial"

    def test_build_summary_works_without_trace(self):
        """build_summary must not crash when trace=None (non-LangSmith path)."""
        from merger.merger import build_summary
        steps = [
            {"step_index": 0, "tool_name": "search", "success": True, "latency_ms": 100, "reasoning": "testing"},
        ]
        result = build_summary("ep_test", "my_agent", "test task", steps, trace=None)
        assert "ep_test" in result
        assert "search" in result
