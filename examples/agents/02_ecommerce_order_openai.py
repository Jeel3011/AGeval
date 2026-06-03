"""
02 — E-commerce Order Agent (OpenAI function calling)

A shopping agent that checks stock, places an order, and charges payment.
Demonstrates a real multi-tool transaction with a guarded payment step.
Exercises get_product, check_inventory, create_order, process_payment, send_email.

Run:  python examples/agents/02_ecommerce_order_openai.py
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import openai_schemas, subset

TOOLS = ["get_product", "check_inventory", "create_order", "process_payment", "send_email"]


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
                "You are an order-fulfilment agent. Verify the item is in stock and "
                "its price before ordering, place the order, charge the customer's "
                "card for the order total, then email a receipt. Never charge before "
                "confirming stock. Reason briefly before each tool call.")},
            {"role": "user", "content": (
                "Order 2 units of SKU-GRN-CAP for buyer jane@shop.example. "
                "Confirm stock, place the order, charge the total, and email the receipt.")},
        ],
        tools=openai_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="ecommerce_order_v1",
        task="order 2x SKU-GRN-CAP and charge the buyer",
        model=OPENAI_MODEL,
        max_iterations=8,
        temperature=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("E-commerce Order Agent (OpenAI)", build_and_run))
