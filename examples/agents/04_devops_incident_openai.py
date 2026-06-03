"""
04 — DevOps Incident Responder (OpenAI function calling)

Triages an incident: probes a service over HTTP, opens a P1 ticket, and
posts to the incident Slack channel. Includes a route that hits an
unreachable host so the agent must recover — this produces a real,
captured env_error in the AGeval trace.

Exercises http_get, create_ticket, post_slack.

Run:  python examples/agents/04_devops_incident_openai.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import openai_schemas, subset

TOOLS = ["http_get", "create_ticket", "post_slack"]


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    from openai import OpenAI

    from ageval import trace_openai

    client = OpenAI()
    return trace_openai(
        client=client,
        messages=[
            {"role": "system", "content": (
                "You are an on-call incident responder. Probe the failing service's "
                "health endpoint. If the probe fails, retry the public status URL, "
                "then open a P1 ticket and post a concise update to #incidents. "
                "Reason briefly before each tool call.")},
            {"role": "user", "content": (
                "Checkout is down. First probe https://checkout.internal/timeout "
                "(it may be unreachable), then fall back to probing "
                "https://status.internal/health, open a P1 ticket titled "
                "'Checkout outage', and post the status to #incidents.")},
        ],
        tools=openai_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="devops_incident_v1",
        task="triage checkout outage with recovery",
        model=OPENAI_MODEL,
        max_iterations=10,
        temperature=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("DevOps Incident Responder (OpenAI)", build_and_run))
