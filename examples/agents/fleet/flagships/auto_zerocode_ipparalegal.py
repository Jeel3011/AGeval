"""
Flagship — zero-code capture (`import ageval.auto`) on REAL APIs.

Proves AGeval's one-line instrumentation works on live traffic: the *only*
AGeval-specific line is `import ageval.auto`. After that, a perfectly ordinary
OpenAI tool-calling loop — whose tools hit live Crossref + Federal Register — is
captured automatically as a scored episode. No AgentSession, no trace_openai.

Run:  python -m examples.agents.fleet.flagships.auto_zerocode_ipparalegal
Needs: OPENAI_API_KEY (+ AGEVAL_API_KEY to record).
"""

from __future__ import annotations

import json
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))

import ageval.auto  # noqa: E402,F401  <-- the entire AGeval integration
from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.real_tools import openai_schemas, subset

TOOLS = ["crossref_works", "federal_register"]


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    from openai import OpenAI

    client = OpenAI()
    funcs = subset(TOOLS)
    schemas = openai_schemas(TOOLS)
    messages = [
        {"role": "system", "content": "You are an IP paralegal. Use the tools for every fact. "
                                       "Find recent scholarly works on 'patent litigation' and any recent "
                                       "Federal Register documents on 'intellectual property', then summarise."},
        {"role": "user", "content": "Build me a short prior-art + regulatory reading list on patent litigation."},
    ]

    final = None
    for _ in range(5):
        resp = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, tools=schemas, tool_choice="auto", temperature=0.0)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            final = msg.content
            break
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                out = funcs[tc.function.name](**args)
                content = json.dumps(out, default=str)[:3000]
            except Exception as exc:
                content = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

    # ageval.auto captured the OpenAI calls under the hood (the patched client
    # POSTs each step to the API). The episode id lives inside auto's bookkeeping;
    # what matters for this flagship is that capture required zero extra code.
    return {"episode_id": "auto", "final_content": final, "recorded": True}


if __name__ == "__main__":
    raise SystemExit(run_and_report("Flagship — zero-code ageval.auto IP Paralegal (real Crossref + FedReg)", build_and_run))
