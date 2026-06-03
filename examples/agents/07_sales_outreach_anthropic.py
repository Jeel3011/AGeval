"""
07 — Sales Outreach Agent (Anthropic / Claude tool use)

Finds the highest-value account, drafts a tailored outreach email, and books
a follow-up meeting. A real go-to-market workflow over Claude tool use.

Exercises sql_query, get_customer, send_email, book_calendar.

Run:  python examples/agents/07_sales_outreach_anthropic.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import ANTHROPIC_MODEL, have_anthropic, require, run_and_report
from examples.agents.toolkit import anthropic_schemas, subset

TOOLS = ["sql_query", "get_customer", "send_email", "book_calendar"]


def build_and_run() -> dict:
    if not require(have_anthropic(), "Anthropic"):
        return {}
    from anthropic import Anthropic

    from ageval import trace_anthropic

    client = Anthropic()
    return trace_anthropic(
        client=client,
        messages=[{"role": "user", "content": (
            "Find our highest-MRR customer, pull their details, send their team a "
            "short upsell email to success@account.example referencing their plan, "
            "and book a 30-minute follow-up titled 'QBR' on 2026-06-20T15:00:00Z.")}],
        tools=anthropic_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="sales_outreach_v1",
        task="identify top account, email, and book QBR",
        model=ANTHROPIC_MODEL,
        max_iterations=8,
        max_tokens=700,
        system=("You are an SDR agent. Use SQL to rank accounts by MRR, then act "
                "on the top one. Keep emails under 80 words."),
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("Sales Outreach Agent (Anthropic)", build_and_run))
