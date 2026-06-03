"""
05 — Financial Analyst Agent (OpenAI function calling)

Answers a revenue question by querying the customer DB, doing real arithmetic
through a calculator tool, and converting the result across currencies. A
data-analysis loop where correctness depends on chaining tool outputs.

Exercises sql_query, calculate, currency_convert.

Run:  python examples/agents/05_financial_analyst_openai.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import openai_schemas, subset

TOOLS = ["sql_query", "calculate", "currency_convert"]


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
                "You are a financial analyst agent. Use SQL to pull the data, the "
                "calculator for every arithmetic step (do not do mental math), and "
                "the FX tool for conversions. Show your reasoning briefly before "
                "each tool call.")},
            {"role": "user", "content": (
                "What is the total monthly recurring revenue across all customers, "
                "and what is that figure in EUR? Pull the MRR values with SQL, sum "
                "them with the calculator, then convert.")},
        ],
        tools=openai_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="financial_analyst_v1",
        task="total MRR in USD and EUR",
        model=OPENAI_MODEL,
        max_iterations=8,
        temperature=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("Financial Analyst Agent (OpenAI)", build_and_run))
