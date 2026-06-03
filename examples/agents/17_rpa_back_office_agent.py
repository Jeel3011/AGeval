"""
17 — Framework-Agnostic RPA Back-Office Agent (AgentSession, real OpenAI planner)

A back-office automation that closes the month: it asks an OpenAI model to
produce a JSON plan of steps, then executes those steps against the toolkit
inside an AgentSession. This is the "bring your own loop" pattern — no agent
framework at all — proving AGeval works for custom/RPA agents too.

It deliberately routes one step through an unreliable upstream so the trace
contains a real, classified env_error and a recovery.

Run:  python examples/agents/17_rpa_back_office_agent.py
Needs: OPENAI_API_KEY (the planner is a real model call).
"""

from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import json

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import (
    create_ticket,
    flaky_inventory_service,
    sql_query,
    write_file,
)

EXECUTORS = {
    "sql_query": lambda a: sql_query(a["query"]),
    "reconcile_inventory": lambda a: flaky_inventory_service(a.get("item", "all")),
    "create_ticket": lambda a: create_ticket(a["subject"], a.get("priority", "P3")),
    "write_file": lambda a: write_file(a["path"], a["content"]),
}


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    from openai import OpenAI

    from ageval import AgentSession

    client = OpenAI()
    # Real model call: produce the automation plan.
    resp = client.chat.completions.create(
        model=OPENAI_MODEL, temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "You are an RPA planner. Output JSON {\"steps\":[{\"action\":..,\"args\":{..},"
                "\"why\":..}]} using only these actions: sql_query(query), "
                "reconcile_inventory(item), create_ticket(subject,priority), "
                "write_file(path,content). reconcile_inventory may fail; if so the runner "
                "will open a ticket. Keep it to 4-5 steps for a month-end close.")},
            {"role": "user", "content": (
                "Close the month: pull all customers via SQL, reconcile inventory for 'all', "
                "write a summary to close.txt, and open a P3 ticket titled 'Month-end review'.")},
        ],
    )
    plan = json.loads(resp.choices[0].message.content).get("steps", [])

    session = AgentSession(agent_id="rpa_back_office_v1", task="month-end close automation")
    session.start()
    for step in plan:
        action = step.get("action")
        args = step.get("args", {}) or {}
        why = step.get("why")
        fn = EXECUTORS.get(action)
        if fn is None:
            session.record_step(tool_name=action or "unknown", tool_input=args, success=False,
                                error_message=f"unknown action {action!r}",
                                error_category="agent_error", is_recoverable=False, reasoning=why)
            continue
        import time as _t
        t0 = _t.perf_counter()
        try:
            out = fn(args)
            session.record_step(tool_name=action, tool_input=args, tool_output=out, success=True,
                                reasoning=why, latency_ms=int((_t.perf_counter() - t0) * 1000))
        except Exception as exc:
            session.record_error(tool_name=action, exc=exc, tool_input=args, reasoning=why,
                                 latency_ms=int((_t.perf_counter() - t0) * 1000))
            # Recovery: the reconcile upstream is flaky → file a ticket and continue.
            session.record_step(tool_name="create_ticket",
                                tool_input={"subject": f"reconcile failed: {action}", "priority": "P2"},
                                tool_output=create_ticket(f"reconcile failed: {action}", "P2"),
                                success=True, reasoning="recover from upstream failure")
    session.finish()
    return {"episode_id": session.episode_id,
            "final_content": f"executed {len(plan)} planned steps (with recovery)"}


if __name__ == "__main__":
    raise SystemExit(run_and_report("RPA Back-Office Agent", build_and_run))
