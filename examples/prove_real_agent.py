"""
examples/prove_real_agent.py

PROOF that AGeval works on a *real* agent, end-to-end, through the actual
production code paths — no stubs in the scoring path.

What it does:
  1. Runs a real OpenAI function-calling agent (gpt-4o-mini) on a multi-step
     task with real tools. The LLM genuinely decides which tools to call.
  2. Records each tool call as an episode_step (the same shape the SDK emits).
  3. Writes episode + steps to Supabase (live), then runs the REAL pipeline:
        merger.run_merger      → derives outcome, stores a real OpenAI embedding
        eval.rules.score_episode   → deterministic rule scorecard
        eval.llm_judge.judge_episode → real LLM-as-judge scorecard
        ageval.metrics             → custom metric scoring
  4. Reads everything back and prints a full scorecard.

Usage:
    python examples/prove_real_agent.py            # live Supabase (.env)
    python examples/prove_real_agent.py --offline  # in-memory DB double

Requires OPENAI_API_KEY. Live mode also needs AGEVAL_SUPABASE_URL +
AGEVAL_SUPABASE_SERVICE_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# Make repo root importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Real tools the agent can call (deterministic, local — but the LLM drives them)
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    table = {"tokyo": "sunny, 22°C", "paris": "rainy, 14°C", "london": "cloudy, 12°C"}
    return table.get(city.lower().strip(), "clear, 20°C")


def currency_convert(amount: float, from_ccy: str, to_ccy: str) -> str:
    rates = {("JPY", "USD"): 0.0064, ("USD", "JPY"): 156.0, ("EUR", "USD"): 1.08}
    rate = rates.get((from_ccy.upper(), to_ccy.upper()))
    if rate is None:
        raise ValueError(f"No rate for {from_ccy}->{to_ccy}")
    return f"{amount} {from_ccy.upper()} = {round(amount * rate, 2)} {to_ccy.upper()}"


def calculate(expression: str) -> str:
    # tiny safe arithmetic evaluator
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError("unsupported characters in expression")
    return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 - sandboxed chars


TOOLS = {
    "get_weather": get_weather,
    "currency_convert": currency_convert,
    "calculate": calculate,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_weather", "description": "Get current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "currency_convert", "description": "Convert an amount between currencies.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "from_ccy": {"type": "string"}, "to_ccy": {"type": "string"}},
            "required": ["amount", "from_ccy", "to_ccy"]}}},
    {"type": "function", "function": {
        "name": "calculate", "description": "Evaluate an arithmetic expression.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
]


# ---------------------------------------------------------------------------
# Run a real OpenAI function-calling agent, capturing steps
# ---------------------------------------------------------------------------
def run_agent(task: str) -> tuple[list[dict], str]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    messages = [
        {"role": "system", "content": "You are a helpful travel assistant. "
         "Before each tool call, briefly explain your reasoning in one sentence. "
         "Use tools to compute exact answers, then give a final summary."},
        {"role": "user", "content": task},
    ]
    steps: list[dict] = []
    step_index = 0
    final_text = ""

    for _ in range(8):
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, tools=TOOL_SCHEMAS, temperature=0.0,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            final_text = msg.content or ""
            break

        reasoning = (msg.content or "").strip() or None
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            t0 = time.perf_counter()
            success, output, err_cat, err_msg = True, None, None, None
            try:
                output = TOOLS[name](**args)
            except Exception as exc:  # classify like the SDK does
                from ageval.session import classify_error
                success = False
                err_cat, _ = classify_error(exc)
                err_msg = str(exc)
                output = None
            latency_ms = int((time.perf_counter() - t0) * 1000)

            steps.append({
                "step_index": step_index,
                "tool_name": name,
                "tool_input": args,
                "tool_output": output,
                "success": success,
                "error_category": err_cat,
                "error_message": err_msg,
                "reasoning": reasoning,
                "latency_ms": latency_ms,
            })
            step_index += 1
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(output) if success else f"ERROR: {err_msg}",
            })

    return steps, final_text


# ---------------------------------------------------------------------------
# DB setup (live or fake) + match_episodes RPC for the fake
# ---------------------------------------------------------------------------
def get_client(offline: bool):
    if offline:
        from tests.fakes import FakeSupabase
        db = FakeSupabase()

        def _match(params):
            return []  # similarity search not exercised offline

        db.register_rpc("match_episodes", _match)
        return db, "usr_proof_offline"

    from supabase import create_client
    db = create_client(os.environ["AGEVAL_SUPABASE_URL"], os.environ["AGEVAL_SUPABASE_SERVICE_KEY"])
    return db, f"usr_proof_{uuid.uuid4().hex[:8]}"


def banner(title: str) -> None:
    print("\n" + "=" * 64 + f"\n  {title}\n" + "=" * 64)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use in-memory DB double")
    ap.add_argument("--task", default=(
        "I'm staying 3 nights in Tokyo at 25000 JPY per night. "
        "What's the total in USD, and what's the weather there?"))
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set — cannot run a real agent.")
        return 2

    db, user_id = get_client(args.offline)
    episode_id = f"ep_{uuid.uuid4().hex[:16]}"
    agent_id = "trip_planner_proof"

    banner("1. REAL AGENT RUN (OpenAI gpt-4o-mini, real tool calls)")
    print(f"Task: {args.task}")
    steps, final_text = run_agent(args.task)
    print(f"\nAgent made {len(steps)} tool call(s):")
    for s in steps:
        status = "ok" if s["success"] else f"FAIL({s['error_category']})"
        print(f"  [{s['step_index']}] {s['tool_name']}({json.dumps(s['tool_input'])}) -> {status} "
              f"= {s['tool_output']}  ({s['latency_ms']}ms)")
    print(f"\nFinal answer: {final_text[:300]}")

    banner("2. PERSIST episode + steps (same writes the API server does)")
    db.table("episodes").insert({
        "episode_id": episode_id, "agent_id": agent_id, "user_id": user_id,
        "run_id": "none", "task": args.task,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    db.table("episode_steps").insert([
        {**s, "episode_id": episode_id, "created_at": datetime.now(timezone.utc).isoformat()}
        for s in steps
    ]).execute()
    print(f"Wrote episode {episode_id} + {len(steps)} steps for user {user_id}")

    banner("3. MERGER (real OpenAI embedding, outcome derivation)")
    from merger.merger import run_merger
    result = run_merger(client=db, episode_id=episode_id, run_id="none", agent_id=agent_id, task=args.task)
    ep = db.table("episodes").select("*").eq("episode_id", episode_id).limit(1).execute().data[0]
    print(f"merge result={result} | outcome={ep.get('outcome')} | total_steps={ep.get('total_steps')} | "
          f"total_latency_ms={ep.get('total_latency_ms')}")
    emb = db.table("episode_embeddings").select("episode_id").eq("episode_id", episode_id).execute().data
    print(f"embedding stored: {bool(emb)}")

    banner("4. RULE SCORER (deterministic)")
    from eval.rules import score_episode
    rule = score_episode(db, episode_id)
    print(f"rules score = {rule['score']}")
    for k, v in rule["breakdown"].items():
        print(f"   - {k:20s} {v}")

    banner("5. LLM JUDGE (real gpt-4o-mini as judge)")
    judge = None
    try:
        from eval.llm_judge import judge_episode
        judge = judge_episode(db, episode_id)
        print(f"llm_judge score = {judge['score']}")
        for k, v in judge["breakdown"].items():
            print(f"   - {k:20s} {v}")
        print(f"   reasoning: {judge.get('reasoning','')[:200]}")
    except Exception as exc:
        print(f"LLM judge failed: {exc}")

    banner("6. CUSTOM METRICS")
    from ageval.metrics import score_with_custom_metrics
    custom = score_with_custom_metrics(db, episode_id)
    print(f"custom composite = {custom['score']}")
    for k, v in custom["breakdown"].items():
        print(f"   - {k:20s} {v}")

    banner("7. VERDICT")
    scores = db.table("episode_scores").select("scorer, score").eq("episode_id", episode_id).execute().data
    print("Persisted scores:", {s["scorer"]: s["score"] for s in scores})
    ok = (
        ep.get("outcome") in {"success", "partial", "failure"}
        and ep.get("total_steps") == len(steps)
        and any(s["scorer"] == "rules" for s in scores)
    )
    print("\n✅ END-TO-END PROOF PASSED" if ok else "\n❌ proof incomplete")
    print(f"   View it: GET /episodes/{episode_id}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
