"""
03 — Travel Concierge Agent (OpenAI function calling)

Plans a short trip: weather, flights, currency, and a calendar hold.
A classic many-tool planning loop with cross-tool data flow.
Exercises get_weather, search_flights, currency_convert, book_calendar.

Run:  python examples/agents/03_travel_concierge_openai.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import openai_schemas, subset

TOOLS = ["get_weather", "search_flights", "currency_convert", "book_calendar"]


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
                "You are a travel concierge. Check the destination weather, find the "
                "cheapest direct flight, convert its price to the traveller's home "
                "currency, and put a calendar hold on the departure. Reason briefly "
                "before each tool call.")},
            {"role": "user", "content": (
                "I'm flying JFK -> NRT on 2026-07-10. What's the Tokyo weather, the "
                "cheapest flight, its price in EUR, and please hold my calendar for "
                "the departure at 2026-07-10T08:00:00Z.")},
        ],
        tools=openai_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="travel_concierge_v1",
        task="plan JFK->NRT trip with weather, flight, FX, calendar",
        model=OPENAI_MODEL,
        max_iterations=10,
        temperature=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("Travel Concierge Agent (OpenAI)", build_and_run))
