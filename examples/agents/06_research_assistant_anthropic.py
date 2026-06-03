"""
06 — RAG Research Assistant (Anthropic / Claude tool use)

A retrieval-augmented assistant that answers policy questions strictly from
the knowledge base. Exercises Claude's tool-use loop through trace_anthropic,
including the hallucination_free / instruction_following judge dimensions.

Exercises vector_search, http_get.

Run:  python examples/agents/06_research_assistant_anthropic.py
Needs: ANTHROPIC_API_KEY (real calls).
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from examples.agents._common import ANTHROPIC_MODEL, have_anthropic, require, run_and_report
from examples.agents.toolkit import anthropic_schemas, subset

TOOLS = ["vector_search", "http_get"]


def build_and_run() -> dict:
    if not require(have_anthropic(), "Anthropic"):
        return {}
    from anthropic import Anthropic

    from ageval import trace_anthropic

    client = Anthropic()
    return trace_anthropic(
        client=client,
        messages=[{"role": "user", "content": (
            "Using only the knowledge base, answer two questions and cite the "
            "passage titles you used: (1) What uptime does the enterprise SLA "
            "guarantee? (2) What are the API rate limits per plan? Do not invent "
            "numbers — if the KB doesn't say, say so.")}],
        tools=anthropic_schemas(TOOLS),
        tool_functions=subset(TOOLS),
        agent_id="research_assistant_v1",
        task="answer SLA + rate-limit questions from KB with citations",
        model=ANTHROPIC_MODEL,
        max_iterations=8,
        max_tokens=700,
        system=("You are a careful research assistant. Retrieve evidence with "
                "vector_search before answering, and ground every claim in a "
                "retrieved passage."),
    )


if __name__ == "__main__":
    raise SystemExit(run_and_report("RAG Research Assistant (Anthropic)", build_and_run))
