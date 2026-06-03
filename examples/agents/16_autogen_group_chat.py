"""
16 — AutoGen Group Chat (real AutoGen / ag2 multi-agent conversation)

A two-agent AutoGen conversation: an AssistantAgent that proposes tool calls
and a UserProxyAgent that executes them. The registered tools are AGeval-traced,
so an AutoGen group chat becomes a scored episode.

Run:  python examples/agents/16_autogen_group_chat.py
Needs: OPENAI_API_KEY, and `pip install pyautogen` (or `autogen-agentchat`).
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import os

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import calculate, get_customer, sql_query


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from autogen import AssistantAgent, UserProxyAgent, register_function
    except ImportError:
        print("  [skip] AutoGen not installed. Run: pip install pyautogen")
        return {}

    from ageval import AgentSession

    session = AgentSession(agent_id="autogen_group_chat_v1",
                           task="answer a revenue question via an AutoGen conversation")
    session.start()

    llm_config = {"config_list": [{"model": OPENAI_MODEL, "api_key": os.environ["OPENAI_API_KEY"]}],
                  "temperature": 0}

    assistant = AssistantAgent(
        name="analyst",
        system_message=("You answer revenue questions. Use run_sql to fetch and calc for math. "
                        "When done, reply with the answer followed by TERMINATE."),
        llm_config=llm_config,
    )
    user = UserProxyAgent(
        name="executor", human_input_mode="NEVER", max_consecutive_auto_reply=6,
        is_termination_msg=lambda m: "TERMINATE" in (m.get("content") or ""),
        code_execution_config=False,
    )

    # Register AGeval-traced tools on the conversation.
    register_function(session.traced(sql_query, reasoning="fetch rows"),
                      caller=assistant, executor=user, name="run_sql",
                      description="Run a read-only SQL SELECT against the customers table.")
    register_function(session.traced(calculate, reasoning="do arithmetic"),
                      caller=assistant, executor=user, name="calc",
                      description="Evaluate an arithmetic expression.")
    register_function(session.traced(get_customer, reasoning="look up a customer"),
                      caller=assistant, executor=user, name="get_customer",
                      description="Look up a customer by id.")

    user.initiate_chat(assistant, message=(
        "What is the combined MRR of the enterprise and growth customers? "
        "Use SQL to fetch them and the calculator to add them."))

    session.finish()
    last = user.last_message().get("content") if user.last_message() else None
    return {"episode_id": session.episode_id, "final_content": last}


if __name__ == "__main__":
    raise SystemExit(run_and_report("AutoGen Group Chat", build_and_run))
