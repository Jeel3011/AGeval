"""
sdk/produce_trace.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

import langsmith
from langsmith import traceable, Client as LangSmithClient
from supabase import create_client
from episodic_sdk import episodic_trace, JobPusher, new_episode_id

sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)
ls = LangSmithClient(api_key=os.environ["LANGSMITH_API_KEY"])

ep_id = new_episode_id()
print(f"\nepisode_id: {ep_id}")

sb.table("episodes").insert({
    "episode_id": ep_id,
    "agent_id"  : "demo_agent_v1",
    "run_id"    : "placeholder",
    "task"      : "add two numbers then reverse a string",
}).execute()


def add_numbers(a: int, b: int) -> int:
    return a + b

def reverse_string(s: str) -> str:
    return s[::-1]


# run_id captured here after the trace completes
captured_run_id = {}

@traceable(name="demo_agent_run", project_name="ageval-demo")
def run_agent(task: str) -> dict:
    results = []

    traced_add = episodic_trace(
        episode_id=ep_id,
        step_index=0,
        llm_output="<reasoning>Adding the two input numbers together</reasoning>",
        swallow_write_errors=False,
    )(add_numbers)

    result_add = traced_add(12, 30)
    results.append(result_add)
    print(f"  step 0 add_numbers(12, 30) = {result_add}")

    traced_rev = episodic_trace(
        episode_id=ep_id,
        step_index=1,
        llm_output="<reasoning>Reversing the task string to verify string manipulation</reasoning>",
        swallow_write_errors=False,
    )(reverse_string)

    result_rev = traced_rev(task)
    results.append(result_rev)
    print(f"  step 1 reverse_string('{task}') = {result_rev}")

    # capture run_id from inside the trace context — most reliable way
    ctx = langsmith.get_current_run_tree()
    if ctx:
        captured_run_id["value"] = str(ctx.id)

    return {"results": results}


print("\nRunning agent (LangSmith is recording)...")
output = run_agent("hello world")
print(f"Agent output: {output}")

# get run_id — from context if available, fallback to list_runs
run_id = captured_run_id.get("value")

if not run_id:
    # fallback: wait a moment for LangSmith to ingest, then query
    print("Context capture missed, querying LangSmith API...")
    import time
    time.sleep(5)
    runs = list(ls.list_runs(
        project_name="ageval-demo",
        run_type="chain",
        limit=5,
    ))
    # match by name in case there are multiple
    for r in runs:
        if r.name == "demo_agent_run":
            run_id = str(r.id)
            break

if not run_id:
    print("\nERROR: Could not get run_id.")
    print("Check smith.langchain.com — did the trace appear in ageval-demo project?")
    print("If not, your LANGSMITH_TRACING env var is not being picked up.")
    exit(1)

print(f"run_id: {run_id}")

# update episodes with real run_id
sb.table("episodes").update({"run_id": run_id}).eq("episode_id", ep_id).execute()

job_id = JobPusher().push(
    episode_id=ep_id,
    run_id=run_id,
    agent_id="demo_agent_v1",
    task="add two numbers then reverse a string",
)

print(f"job_id: {job_id}")
print("\n── copy these into merger test ───────────────────────────────")
print(f"episode_id = \"{ep_id}\"")
print(f"run_id     = \"{run_id}\"")
print("──────────────────────────────────────────────────────────────\n")