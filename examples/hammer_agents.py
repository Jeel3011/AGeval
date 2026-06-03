"""
examples/hammer_agents.py

Hard end-to-end stress test of AGeval against REAL LLM agents, exercising the
new framework adapters (trace_openai / trace_anthropic) through the live API
server and the real scoring pipeline.

Scenarios (each a distinct, real agent run):
  A. multi_tool      — normal multi-step OpenAI agent (weather + currency + math)
  B. error_injection — a tool deliberately raises; proves error capture + recovery
  C. long_runner     — a ~15-20 step OpenAI agent (deep loop) to stress step volume
  D. anthropic_tool  — real Claude tool-use agent (skipped if no ANTHROPIC_API_KEY)

For each: the adapter records the episode to the live API → we run the real
merger + rule scorer + LLM judge + custom metrics → we read the scores back and
assert the pipeline produced a sane, persisted result.

Usage:
    python examples/hammer_agents.py            # talks to API at AGEVAL_API_URL
    python examples/hammer_agents.py --base http://localhost:8000

Requires: a running AGeval API server with live Supabase, an AGEVAL_API_KEY for
that server, and OPENAI_API_KEY. ANTHROPIC_API_KEY is optional.
The companion runner (run_hammer.sh) boots a local server + key for you.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    table = {"tokyo": "sunny, 22C", "paris": "rainy, 14C", "london": "cloudy, 12C"}
    return table.get(city.lower().strip(), "clear, 20C")


def currency_convert(amount: float, from_ccy: str, to_ccy: str) -> str:
    rates = {("JPY", "USD"): 0.0064, ("USD", "JPY"): 156.0, ("EUR", "USD"): 1.08}
    rate = rates.get((from_ccy.upper(), to_ccy.upper()))
    if rate is None:
        raise ValueError(f"No rate for {from_ccy}->{to_ccy}")
    return f"{amount} {from_ccy.upper()} = {round(amount * rate, 2)} {to_ccy.upper()}"


def calculate(expression: str) -> str:
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError("unsupported characters")
    return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307


def flaky_lookup(item: str) -> str:
    # Always raises — used to prove error capture/classification on a real run.
    raise ConnectionError("upstream timeout contacting inventory service")


OAI_SCHEMAS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "currency_convert", "description": "Convert currency.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "from_ccy": {"type": "string"}, "to_ccy": {"type": "string"}},
            "required": ["amount", "from_ccy", "to_ccy"]}}},
    {"type": "function", "function": {"name": "calculate", "description": "Evaluate arithmetic.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"type": "function", "function": {"name": "flaky_lookup", "description": "Look up an item in inventory.",
        "parameters": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}}},
]

ANT_SCHEMAS = [
    {"name": "get_weather", "description": "Weather for a city.",
     "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"name": "calculate", "description": "Evaluate arithmetic.",
     "input_schema": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}},
]

TOOLS = {
    "get_weather": get_weather, "currency_convert": currency_convert,
    "calculate": calculate, "flaky_lookup": flaky_lookup,
}


def banner(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


def get_db():
    from supabase import create_client
    return create_client(os.environ["AGEVAL_SUPABASE_URL"], os.environ["AGEVAL_SUPABASE_SERVICE_KEY"])


def score_and_verify(db, episode_id: str, expect_min_steps: int) -> dict:
    """Run the real pipeline on a recorded episode and assert it produced scores."""
    from merger.merger import run_merger
    from eval.rules import score_episode
    from ageval.metrics import score_with_custom_metrics

    run_merger(client=db, episode_id=episode_id, run_id="none", agent_id="hammer", task="hammer")
    ep = db.table("episodes").select("*").eq("episode_id", episode_id).limit(1).execute().data
    assert ep, f"episode {episode_id} not found after merge"
    ep = ep[0]

    # Run the deterministic scorers (they persist to episode_scores).
    score_episode(db, episode_id)
    score_with_custom_metrics(db, episode_id)

    try:
        from eval.llm_judge import judge_episode
        judge_episode(db, episode_id)  # persists scorer='llm_judge'
    except Exception as exc:
        print(f"   (llm judge skipped: {exc})")

    scores = {s["scorer"]: float(s["score"])
              for s in db.table("episode_scores").select("scorer, score").eq("episode_id", episode_id).execute().data}

    print(f"   outcome={ep.get('outcome')} steps={ep.get('total_steps')} "
          f"latency={ep.get('total_latency_ms')}ms")
    print(f"   scores: {scores}")

    assert ep.get("outcome") in {"success", "partial", "failure"}, "no outcome derived"
    assert (ep.get("total_steps") or 0) >= expect_min_steps, "fewer steps than expected"
    assert "rules" in scores and "custom" in scores, "rule/custom scores missing"
    for name, val in scores.items():
        assert 0.0 <= val <= 1.0, f"{name} score out of range: {val}"
    return {"episode_id": episode_id, "scores": scores, "outcome": ep.get("outcome")}


def run_openai(messages, task, max_iterations=10):
    from openai import OpenAI
    from ageval import trace_openai
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return trace_openai(
        client=client, messages=messages, tools=OAI_SCHEMAS, tool_functions=TOOLS,
        agent_id="hammer", task=task, model="gpt-4o-mini", max_iterations=max_iterations,
        temperature=0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AGEVAL_API_URL", "http://localhost:8000"))
    ap.add_argument("--no-anthropic", action="store_true")
    args = ap.parse_args()
    os.environ["AGEVAL_API_URL"] = args.base

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set — cannot run real agents.")
        return 2
    if not os.environ.get("AGEVAL_API_KEY"):
        print("AGEVAL_API_KEY not set — start the server + register a key first.")
        return 2

    db = get_db()
    results = []
    t_start = time.time()

    # --- A. multi-tool ---
    banner("A. multi_tool — normal multi-step OpenAI agent")
    r = run_openai(
        [{"role": "system", "content": "You are a precise travel assistant. Reason in one sentence before each tool call."},
         {"role": "user", "content": "3 nights in Tokyo at 25000 JPY/night — total in USD? And the weather there?"}],
        "tokyo trip cost + weather",
    )
    print(f"   episode={r['episode_id']} final={str(r['final_content'])[:120]}")
    results.append(score_and_verify(db, r["episode_id"], expect_min_steps=2))

    # --- B. error injection ---
    banner("B. error_injection — a tool deliberately fails on a real run")
    r = run_openai(
        [{"role": "system", "content": "You are an inventory assistant. If a lookup fails, explain and try the calculator instead."},
         {"role": "user", "content": "Look up item 'widget-9' with flaky_lookup, then compute 12*7 with the calculator."}],
        "inventory lookup with failure",
    )
    print(f"   episode={r['episode_id']} final={str(r['final_content'])[:120]}")
    res_b = score_and_verify(db, r["episode_id"], expect_min_steps=2)
    # Confirm a failed step was actually captured.
    steps_b = db.table("episode_steps").select("tool_name, success, error_category").eq("episode_id", r["episode_id"]).execute().data
    failures = [s for s in steps_b if not s["success"]]
    print(f"   captured {len(failures)} failed step(s): {[(s['tool_name'], s['error_category']) for s in failures]}")
    assert failures, "error-injection run recorded no failures — error capture broken!"
    results.append(res_b)

    # --- C. long runner ---
    banner("C. long_runner — deep multi-step agent (many calculations)")
    nums = " then ".join([f"compute {i}*{i}" for i in range(2, 12)])
    r = run_openai(
        [{"role": "system", "content": "You are a calculator agent. Use the calculate tool for EACH computation separately, one tool call at a time. Reason briefly before each."},
         {"role": "user", "content": f"Do these one at a time using the calculator: {nums}. Then give all results."}],
        "long calculation chain",
        max_iterations=16,
    )
    print(f"   episode={r['episode_id']} final={str(r['final_content'])[:120]}")
    results.append(score_and_verify(db, r["episode_id"], expect_min_steps=5))

    # --- D. anthropic ---
    if not args.no_anthropic and os.environ.get("ANTHROPIC_API_KEY"):
        banner("D. anthropic_tool — real Claude tool-use agent")
        from anthropic import Anthropic
        from ageval import trace_anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        r = trace_anthropic(
            client=client,
            messages=[{"role": "user", "content": "What's the weather in Paris, and what is 144/12? Use the tools."}],
            tools=ANT_SCHEMAS, tool_functions=TOOLS, agent_id="hammer",
            task="paris weather + math", model="claude-haiku-4-5-20251001", max_iterations=8,
        )
        print(f"   episode={r['episode_id']} final={str(r['final_content'])[:120]} tokens={r['usage']}")
        results.append(score_and_verify(db, r["episode_id"], expect_min_steps=2))
    else:
        print("\n(D. anthropic_tool skipped — no ANTHROPIC_API_KEY)")

    banner("VERDICT")
    print(f"Ran {len(results)} real-agent scenarios in {time.time() - t_start:.1f}s")
    for res in results:
        print(f"  ✓ {res['episode_id']}  outcome={res['outcome']}  scores={res['scores']}")
    print("\n✅ LIVE MULTI-AGENT HAMMER TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
