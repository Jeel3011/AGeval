"""
01 — Customer Support Agent (OpenAI function calling)

A Tier-1 support agent: looks the customer up, searches the knowledge base,
and opens a ticket if it can't resolve the issue. Exercises sql_query,
get_customer, vector_search, create_ticket, send_email.

Run:  python examples/agents/01_customer_support_openai.py
Needs: OPENAI_API_KEY (real calls). AGEVAL_API_KEY to record to AGeval.
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import openai_schemas, subset

TOOLS = ["get_customer", "vector_search", "sql_query", "create_ticket", "send_email"]


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
                "You are a Tier-1 customer support agent. Identify the customer, "
                "search the knowledge base for relevant policy, and resolve the "
                "request. If you cannot resolve it, open a support ticket and email "
                "the customer a summary. Reason briefly before each tool call.")},
            {"role": "user", "content": (
                "Customer C-1001 is asking whether they're covered by the enterprise "
                "SLA after an outage, and wants a refund for downtime. Look them up, "
                "check the policy, and if a refund isn't automatic, open a P2 ticket "
                "and email them at ops@acme.example.")},
        ],
        tools=openai_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="customer_support_v1",
        task="resolve SLA/refund request for C-1001",
        model=OPENAI_MODEL,
        max_iterations=8,
        temperature=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("Customer Support Agent (OpenAI)", build_and_run))
