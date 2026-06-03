"""
tests/test_tracers.py

Unit tests for the framework adapters (trace_openai, trace_anthropic).

These run fully offline: the LLM clients are fakes, and the AGeval API POST is
monkeypatched to capture the steps that *would* be sent to the server. The key
behaviours under test:

  1. The tool-use loop runs to completion and executes the user's tool fns.
  2. reasoning_coverage is NOT silently 0 for tool-calling agents — every tool
     step carries the attributed reasoning (regression test for the OpenAI
     null-content bug).
  3. Errors raised by user tools are recorded as failed steps, not swallowed.
"""

from __future__ import annotations

import json
import types

import pytest

import ageval.session as session_mod
from ageval.openai_tracer import trace_openai
from ageval.anthropic_tracer import trace_anthropic


# ---------------------------------------------------------------------------
# Capture harness: make the SDK "configured" and record every posted step.
# ---------------------------------------------------------------------------
@pytest.fixture
def captured(monkeypatch):
    posts: list[tuple[str, object]] = []

    def fake_post(path, payload, *, swallow=True):
        posts.append((path, payload))
        return {"ok": True}

    monkeypatch.setenv("AGEVAL_API_KEY", "ageval-sk-test")
    monkeypatch.setattr(session_mod, "_post", fake_post)
    # finish() spawns a daemon thread that calls _post for /jobs; that's fine —
    # it uses the same patched fn. Join isn't needed because we read posts that
    # are appended synchronously during the loop (steps batch on __exit__).
    return posts


def _steps_from(posts):
    """Flatten the /steps and /steps/batch payloads into a list of step dicts."""
    steps = []
    for path, payload in posts:
        if path == "/steps/batch":
            steps.extend(payload)
        elif path == "/steps":
            steps.append(payload)
    return steps


# ---------------------------------------------------------------------------
# Fake OpenAI client
# ---------------------------------------------------------------------------
def _oai_msg(content=None, tool_calls=None):
    m = types.SimpleNamespace()
    m.content = content
    m.tool_calls = tool_calls
    m.model_dump = lambda: {"role": "assistant", "content": content}
    return m


def _oai_tool_call(call_id, name, args: dict):
    fn = types.SimpleNamespace(name=name, arguments=json.dumps(args))
    return types.SimpleNamespace(id=call_id, function=fn)


class FakeOpenAI:
    """Returns scripted responses: first a tool call, then a final answer."""

    def __init__(self):
        self._turn = 0
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self._turn += 1
        if self._turn == 1:
            # Tool-calling turn: content is None (the real-world bug trigger).
            msg = _oai_msg(content=None, tool_calls=[_oai_tool_call("c1", "get_weather", {"city": "Paris"})])
            choice = types.SimpleNamespace(message=msg, finish_reason="tool_calls")
        else:
            msg = _oai_msg(content="It is sunny in Paris.", tool_calls=None)
            choice = types.SimpleNamespace(message=msg, finish_reason="stop")
        return types.SimpleNamespace(choices=[choice])


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------
def _ant_text(text):
    return types.SimpleNamespace(type="text", text=text)


def _ant_tool_use(uid, name, inp):
    return types.SimpleNamespace(type="tool_use", id=uid, name=name, input=inp)


class FakeAnthropic:
    def __init__(self):
        self._turn = 0
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self._turn += 1
        usage = types.SimpleNamespace(input_tokens=10, output_tokens=5)
        if self._turn == 1:
            # Claude often interleaves a short rationale with the tool_use.
            content = [
                _ant_text("I should look up the weather."),
                _ant_tool_use("tu1", "get_weather", {"city": "Paris"}),
            ]
            return types.SimpleNamespace(content=content, stop_reason="tool_use", usage=usage)
        content = [_ant_text("It is sunny in Paris.")]
        return types.SimpleNamespace(content=content, stop_reason="end_turn", usage=usage)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def get_weather(city):
    return {"city": city, "temp_c": 21, "sky": "clear"}


def test_openai_tool_loop_records_steps_with_reasoning(captured):
    result = trace_openai(
        client=FakeOpenAI(),
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
        tools=[{"type": "function", "function": {"name": "get_weather"}}],
        tool_functions={"get_weather": get_weather},
        agent_id="weather_v1",
        task="weather",
    )
    assert result["episode_id"]
    assert result["final_content"] == "It is sunny in Paris."

    steps = _steps_from(captured)
    tool_steps = [s for s in steps if s["tool_name"] == "get_weather"]
    assert len(tool_steps) == 1
    # Regression: the tool step must NOT have empty reasoning even though the
    # assistant message that triggered it had content=None.
    assert tool_steps[0]["reasoning"], "tool step reasoning was empty (regression)"
    assert tool_steps[0]["success"] is True


def test_anthropic_tool_loop_records_steps_with_reasoning(captured):
    result = trace_anthropic(
        client=FakeAnthropic(),
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
        tools=[{"name": "get_weather", "description": "x", "input_schema": {}}],
        tool_functions={"get_weather": get_weather},
        agent_id="weather_v1",
        task="weather",
    )
    assert result["episode_id"]
    assert result["final_content"] == "It is sunny in Paris."
    assert result["usage"]["output_tokens"] == 10  # 5 per turn × 2 turns

    steps = _steps_from(captured)
    tool_steps = [s for s in steps if s["tool_name"] == "get_weather"]
    assert len(tool_steps) == 1
    assert tool_steps[0]["reasoning"] == "I should look up the weather."
    assert tool_steps[0]["tool_output"] == {"city": "Paris", "temp_c": 21, "sky": "clear"}


def test_anthropic_records_tool_error(captured):
    def boom(city):
        raise ValueError("bad city")

    trace_anthropic(
        client=FakeAnthropic(),
        messages=[{"role": "user", "content": "weather?"}],
        tools=[{"name": "get_weather", "input_schema": {}}],
        tool_functions={"get_weather": boom},
        agent_id="weather_v1",
        task="weather",
    )
    steps = _steps_from(captured)
    failed = [s for s in steps if s["tool_name"] == "get_weather" and not s["success"]]
    assert len(failed) == 1
    assert failed[0]["error_category"] == "agent_error"  # ValueError → agent_error


def test_tracers_no_apikey_falls_through(monkeypatch):
    """Without AGEVAL_API_KEY, the loop still runs but records nothing."""
    monkeypatch.delenv("AGEVAL_API_KEY", raising=False)
    result = trace_anthropic(
        client=FakeAnthropic(),
        messages=[{"role": "user", "content": "weather?"}],
        tools=[{"name": "get_weather", "input_schema": {}}],
        tool_functions={"get_weather": get_weather},
        agent_id="weather_v1",
        task="weather",
    )
    assert result["episode_id"] is None
