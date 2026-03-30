"""
example_agent.py
Shows how to wire episodic_sdk into a generic agent run loop.

This is NOT a working agent — it's a wiring reference.
Replace the placeholder calls with your actual framework's API.
"""

from sdk.episodic_sdk import (
    episodic_trace,
    async_episodic_trace,
    JobPusher,
    new_episode_id,
    ReasoningExtractor,
)

# ----------------------------------------------------------------
# Setup: one episode_id per agent run, generated at the start.
# ----------------------------------------------------------------
episode_id = new_episode_id()  # e.g. "ep_3f8a1c2d4e5b6f7a"


# ----------------------------------------------------------------
# Pattern A: decorator at definition time (static step_index)
#
# Use this if your agent tools are fixed, not dynamic.
# The decorator is applied once; step_index is baked in.
# Problem: step_index is always 0 here. Fine for a single-tool
# demo, wrong for a multi-step loop. See Pattern B for that.
# ----------------------------------------------------------------
@episodic_trace(episode_id=episode_id, step_index=0)
def search_web(query: str) -> str:
    # your actual implementation
    import requests
    return requests.get(f"https://api.example.com?q={query}").text


# ----------------------------------------------------------------
# Pattern B: wrap dynamically inside the agent loop (RECOMMENDED)
#
# This is the real pattern for a multi-step agent where step_index
# increments each iteration and llm_output changes each time.
# ----------------------------------------------------------------
def run_agent(task: str, langsmith_run_id: str) -> dict:
    """
    Skeleton of a generic agent run loop.
    Replace the framework-specific calls with your actual SDK.
    """

    results = []
    step_index = 0

    # Simulated agent loop
    while True:
        # 1. Call your LLM to get the next action
        llm_response = call_llm(task, history=results)  # your framework's call

        # Check for terminal condition
        if is_finished(llm_response):
            break

        # 2. Extract reasoning BEFORE calling the tool
        reasoning_text = ReasoningExtractor.extract(llm_response.raw_text)
        # If your framework doesn't expose raw_text, pass None.
        # reasoning will be null in the DB — that's fine, don't fake it.

        # 3. Identify which tool to call
        tool_fn, tool_args = parse_tool_call(llm_response)  # your framework

        # 4. Wrap the tool dynamically with the current step_index and reasoning
        traced_tool = episodic_trace(
            episode_id=episode_id,
            step_index=step_index,
            llm_output=llm_response.raw_text,
            swallow_write_errors=True,   # don't crash agent on DB hiccup
        )(tool_fn)

        # 5. Call it — SDK captures input/output/error/latency automatically
        try:
            output = traced_tool(**tool_args)
            results.append({"step": step_index, "output": output, "success": True})
        except Exception as e:
            results.append({"step": step_index, "error": str(e), "success": False})
            # Decide: break or continue based on is_recoverable?
            # The DB already has error_category and is_recoverable written.

        step_index += 1

    # 6. Push job to queue — triggers the merger worker
    job_id = JobPusher().push(
        episode_id=episode_id,
        run_id=langsmith_run_id,    # get this from your LangSmith client
        agent_id="my_agent_v1",
        task=task,
    )

    return {"episode_id": episode_id, "job_id": job_id, "steps": step_index}


# ----------------------------------------------------------------
# Async variant — same pattern, different decorator
# ----------------------------------------------------------------
async def run_agent_async(task: str, langsmith_run_id: str) -> dict:
    results = []
    step_index = 0

    while True:
        llm_response = await call_llm_async(task, history=results)

        if is_finished(llm_response):
            break

        tool_fn, tool_args = parse_tool_call(llm_response)

        traced_tool = async_episodic_trace(
            episode_id=episode_id,
            step_index=step_index,
            llm_output=llm_response.raw_text,
        )(tool_fn)

        try:
            output = await traced_tool(**tool_args)
            results.append({"step": step_index, "output": output, "success": True})
        except Exception as e:
            results.append({"step": step_index, "error": str(e), "success": False})

        step_index += 1

    JobPusher().push(
        episode_id=episode_id,
        run_id=langsmith_run_id,
        agent_id="my_agent_v1",
        task=task,
    )

    return {"episode_id": episode_id, "steps": step_index}


# ----------------------------------------------------------------
# Stubs — replace with your actual framework calls
# ----------------------------------------------------------------
def call_llm(task, history): ...
async def call_llm_async(task, history): ...
def is_finished(response): ...
def parse_tool_call(response): ...