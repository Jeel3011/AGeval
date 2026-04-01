import os
from dotenv import load_dotenv
load_dotenv()

from sdk.episodic_sdk import episodic_trace, JobPusher, new_episode_id, EpisodeSession

ep_id = new_episode_id()
print(f"episode_id: {ep_id}")

# create episode via API (no direct Supabase)
from sdk.episodic_sdk import _post
_post("/episodes", {"episode_id": ep_id, "agent_id": "test_agent", "task": "sdk smoke test"})
print("episode created via API")

# --- test 1: successful tool call ---
@episodic_trace(episode_id=ep_id, step_index=0, swallow_write_errors=False)
def good_tool(x: int) -> int:
    return x * 2

result = good_tool(5)
print(f"good_tool returned: {result}")   # should print 10

# --- test 2: tool that raises ValueError (should classify as agent_error) ---
@episodic_trace(episode_id=ep_id, step_index=1, swallow_write_errors=False)
def bad_tool(x: int) -> int:
    raise ValueError("invalid input: x must be positive")

try:
    bad_tool(-1)
except ValueError:
    print("bad_tool raised ValueError as expected")

# --- test 3: tool that raises ConnectionError (should classify as env_error) ---
@episodic_trace(episode_id=ep_id, step_index=2, swallow_write_errors=False)
def flaky_tool() -> str:
    raise ConnectionError("connection refused by remote host")

try:
    flaky_tool()
except ConnectionError:
    print("flaky_tool raised ConnectionError as expected")

# --- push job ---
job_id = JobPusher().push(
    episode_id=ep_id,
    run_id="test_run_001",
    agent_id="test_agent",
    task="sdk smoke test",
)
print(f"job pushed: {job_id}")

print("\nDone. Now check Supabase:")
print(f"  episode_steps → filter by episode_id = '{ep_id}'")
print(f"  episode_jobs  → filter by episode_id = '{ep_id}'")