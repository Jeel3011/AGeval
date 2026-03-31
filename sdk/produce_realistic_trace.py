"""
sdk/produce_realistic_trace.py

Produces a realistic episode with:
  - one env_error (connection failure) that recovers
  - one agent_error (bad input) that does not recover
  - one step with no reasoning
  - one repeated tool call (efficiency penalty)
"""

import os
from dotenv import load_dotenv
load_dotenv()

import langsmith
from langsmith import traceable, Client as LangSmithClient
from supabase import create_client
from episodic_sdk import episodic_trace, JobPusher, new_episode_id

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
ls = LangSmithClient(api_key=os.environ["LANGSMITH_API_KEY"])

ep_id = new_episode_id()
print(f"episode_id: {ep_id}")

sb.table("episodes").insert({
    "episode_id": ep_id,
    "agent_id"  : "demo_agent_v1",
    "run_id"    : "placeholder",
    "task"      : "realistic failure scenario",
}).execute()

captured_run_id = {}

# ── tool definitions ───────────────────────────────────────────────────────

call_count = {"fetch": 0}

def fetch_data(url: str) -> str:
    call_count["fetch"] += 1
    if call_count["fetch"] == 1:
        # first call: simulates a transient network failure
        raise ConnectionError("connection refused by remote host")
    return f"data from {url}"

def parse_result(data: str) -> dict:
    if not data:
        raise ValueError("cannot parse empty data")
    return {"parsed": True, "length": len(data)}

def summarise(data: str) -> str:
    return f"summary of: {data[:20]}"


@traceable(name="realistic_agent_run", project_name="ageval-demo")
def run_agent(task: str) -> dict:
    step = 0
    results = []

    # step 0: fetch fails with env_error (connection refused)
    traced = episodic_trace(
        episode_id=ep_id, step_index=step,
        llm_output="<reasoning>Fetching remote data to begin task</reasoning>",
        swallow_write_errors=False,
    )(fetch_data)
    try:
        results.append(traced("https://api.example.com/data"))
    except ConnectionError:
        print(f"  step {step} fetch_data → ConnectionError (env_error, expected)")
    step += 1

    # step 1: fetch retried — succeeds this time (recovery)
    traced = episodic_trace(
        episode_id=ep_id, step_index=step,
        llm_output="<reasoning>Retrying fetch after transient failure</reasoning>",
        swallow_write_errors=False,
    )(fetch_data)
    r = traced("https://api.example.com/data")
    results.append(r)
    print(f"  step {step} fetch_data → success (recovered)")
    step += 1

    # step 2: parse — no reasoning passed (coverage penalty)
    traced = episodic_trace(
        episode_id=ep_id, step_index=step,
        llm_output=None,   # deliberately no reasoning
        swallow_write_errors=False,
    )(parse_result)
    r = traced(r)
    results.append(r)
    print(f"  step {step} parse_result → success (no reasoning)")
    step += 1

    # step 3: summarise once
    traced = episodic_trace(
        episode_id=ep_id, step_index=step,
        llm_output="<reasoning>Summarising parsed result for output</reasoning>",
        swallow_write_errors=False,
    )(summarise)
    r = traced("some fetched data string")
    results.append(r)
    print(f"  step {step} summarise → success")
    step += 1

    # step 4: summarise again — same tool back to back (efficiency penalty)
    traced = episodic_trace(
        episode_id=ep_id, step_index=step,
        llm_output="<reasoning>Summarising again with different input</reasoning>",
        swallow_write_errors=False,
    )(summarise)
    r = traced("another string to summarise")
    results.append(r)
    print(f"  step {step} summarise → success (duplicate tool, efficiency penalty)")
    step += 1

    ctx = langsmith.get_current_run_tree()
    if ctx:
        captured_run_id["value"] = str(ctx.id)

    return {"results": len(results)}


print("\nRunning realistic agent...")
run_agent("realistic failure scenario")

run_id = captured_run_id.get("value")
if not run_id:
    import time; time.sleep(5)
    runs = list(ls.list_runs(project_name="ageval-demo", run_type="chain", limit=5))
    for r in runs:
        if r.name == "realistic_agent_run":
            run_id = str(r.id); break

if not run_id:
    print("ERROR: could not get run_id"); exit(1)

sb.table("episodes").update({"run_id": run_id}).eq("episode_id", ep_id).execute()
JobPusher().push(episode_id=ep_id, run_id=run_id, agent_id="demo_agent_v1", task="realistic failure scenario")

print(f"\nepisode_id = \"{ep_id}\"")
print(f"run_id     = \"{run_id}\"")
print("\nNow run the worker: python -m merger.worker")