"""
eval/test_rules.py

Run from project root:
    python -m eval.test_rules
"""

import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from eval.rules import score_episode

client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

# ── Test 1: score the real episode from your pipeline ─────────────────────
print("── Test 1: real episode ──────────────────────────────────────")
result = score_episode(client, "ep_150b4afaaf814679")
print(f"score     : {result['score']}")
print(f"breakdown : {result['breakdown']}")
print()

# ── Test 2: simulate a bad episode with injected step data ────────────────
# We don't write to DB for this — just call the metric functions directly
# to verify they produce correct values on known inputs.
print("── Test 2: metric unit checks ────────────────────────────────")

from eval.rules import (
    calc_success_rate,
    calc_recovery_rate,
    calc_reasoning_coverage,
    calc_efficiency_score,
)

bad_steps = [
    {"step_index": 0, "tool_name": "search", "success": False, "error_category": "env_error",   "reasoning": "need to search", "latency_ms": 100},
    {"step_index": 1, "tool_name": "search", "success": True,  "error_category": None,           "reasoning": "retrying search", "latency_ms": 80},
    {"step_index": 2, "tool_name": "search", "success": True,  "error_category": None,           "reasoning": None,              "latency_ms": 90},
    {"step_index": 3, "tool_name": "parse",  "success": False, "error_category": "agent_error",  "reasoning": "parse result",    "latency_ms": 10},
    {"step_index": 4, "tool_name": "parse",  "success": False, "error_category": "agent_error",  "reasoning": None,              "latency_ms": 12},
]

sr = calc_success_rate(bad_steps)
rr = calc_recovery_rate(bad_steps)
rc = calc_reasoning_coverage(bad_steps)
ef = calc_efficiency_score(bad_steps)

print(f"success_rate       : {sr}  (expected 0.4  — 2 of 5 succeeded)")
print(f"recovery_rate      : {rr}  (expected 1.0  — the one env_error was followed by success)")
print(f"reasoning_coverage : {rc}  (expected 0.6  — 3 of 5 have reasoning)")
print(f"efficiency_score   : {ef}  (expected 0.25 — 3 consecutive duplicates in 4 pairs)")

assert sr == 0.4,  f"success_rate wrong: {sr}"
assert rr == 1.0,  f"recovery_rate wrong: {rr}"
assert rc == 0.6,  f"reasoning_coverage wrong: {rc}"
assert ef == 0.25, f"efficiency_score wrong: {ef}"

print("\nAll assertions passed.")
print("\nCheck Supabase episode_scores table for the Test 1 result.")