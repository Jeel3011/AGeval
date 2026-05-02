"""
real_agent_test.py — Test AGeval with a REAL LangGraph agent.

This builds a simple trip planner agent with actual tools,
runs it through trace_agent(), and verifies the full pipeline:

  1. agent.invoke() → LLM makes real decisions
  2. trace_agent() captures every tool call automatically
  3. Steps are written to Supabase via API
  4. Job is pushed to the merger queue
  5. We verify everything landed correctly

Run:
    AGEVAL_API_URL=http://localhost:8000 python real_agent_test.py
"""

import os
import json
import time
import urllib.request
from dotenv import load_dotenv
load_dotenv()

# ── 1. Build a real LangGraph ReAct agent ────────────────────────

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def search_flights(destination: str) -> str:
    """Search for available flights to a destination city."""
    # Simulated real tool — in production this would hit an API
    flights = {
        "paris": "Air France AF101 - $450 | Delta DL200 - $520 | United UA305 - $480",
        "tokyo": "ANA NH10 - $890 | JAL JL001 - $920 | United UA837 - $850",
        "london": "British Airways BA115 - $380 | Virgin VS3 - $410 | American AA100 - $395",
    }
    key = destination.lower().strip()
    return flights.get(key, f"No flights found to {destination}. Try Paris, Tokyo, or London.")


@tool
def search_hotels(city: str, budget: str) -> str:
    """Search for hotels in a city within a budget range."""
    hotels = {
        "paris": "Hotel Le Marais ($120/night, 4.5★) | Citadines Apart ($95/night, 4.2★) | Pullman Tour Eiffel ($210/night, 4.7★)",
        "tokyo": "Shinjuku Granbell ($85/night, 4.3★) | Park Hyatt ($350/night, 4.9★) | Dormy Inn ($70/night, 4.1★)",
        "london": "Premier Inn ($90/night, 4.0★) | The Hoxton ($180/night, 4.6★) | Zetter Townhouse ($220/night, 4.8★)",
    }
    key = city.lower().strip()
    return hotels.get(key, f"No hotels found in {city}.")


@tool
def get_weather(city: str) -> str:
    """Get the current weather forecast for a city."""
    weather = {
        "paris": "Partly cloudy, 18°C. Light rain expected Thursday. Pack a light jacket.",
        "tokyo": "Sunny, 24°C. Clear skies all week. Great weather for sightseeing.",
        "london": "Overcast, 14°C. Rain likely Tuesday-Wednesday. Bring an umbrella.",
    }
    key = city.lower().strip()
    return weather.get(key, f"Weather data unavailable for {city}.")


# Build the agent
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [search_flights, search_hotels, get_weather]
agent = create_react_agent(llm, tools)


# ── 2. Run it through trace_agent() ─────────────────────────────

from ageval import trace_agent

API_BASE = os.environ.get("AGEVAL_API_URL", "http://localhost:8000")
API_KEY  = os.environ["AGEVAL_API_KEY"]

print("\n" + "=" * 60)
print("AGeval REAL Agent Test — Trip Planner")
print(f"API: {API_BASE}")
print("=" * 60)

print("\n🤖 Running real LangGraph agent through trace_agent()...")
print("   Task: 'Plan a 5-day trip to Paris on a moderate budget'\n")

start = time.time()
result = trace_agent(
    agent    = agent,
    input    = {"messages": [("user", "Plan a 5-day trip to Paris on a moderate budget. Search for flights, hotels, and check the weather.")]},
    agent_id = "trip_planner_v1",
    task     = "Plan a 5-day trip to Paris on a moderate budget",
)
elapsed = time.time() - start

print(f"⏱  Agent finished in {elapsed:.1f}s\n")


# ── 3. Extract and display the agent's response ─────────────────

final_message = result["messages"][-1]
print("📝 Agent's final response:")
print("-" * 40)
content = final_message.content if hasattr(final_message, 'content') else str(final_message)
# Show first 500 chars of the response
print(content[:500])
if len(content) > 500:
    print(f"  ... ({len(content)} chars total)")
print("-" * 40)


# ── 4. Verify the data landed in AGeval ──────────────────────────

print("\n🔍 Verifying data in AGeval API...")
time.sleep(2)  # Give the background thread time to push the job

def api_get(path):
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# Get most recent episodes
episodes = api_get("/episodes?limit=5")
recent = episodes["episodes"]

# Find our episode (agent_id = trip_planner_v1, most recent)
our_episode = None
for ep in recent:
    if ep["agent_id"] == "trip_planner_v1":
        our_episode = ep
        break

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        print(f"  ✅  {name}")
        PASS += 1
    else:
        print(f"  ❌  {name}")
        FAIL += 1

check("Episode found in AGeval", our_episode is not None)

if our_episode:
    ep_id = our_episode["episode_id"]
    print(f"  📋  Episode ID: {ep_id}")
    check("agent_id is trip_planner_v1", our_episode["agent_id"] == "trip_planner_v1")
    check("task is recorded", our_episode.get("task") is not None)

    # Get episode detail
    detail = api_get(f"/episodes/{ep_id}")
    steps  = detail.get("steps", [])

    check("Steps were captured (> 0)", len(steps) > 0)
    print(f"  📊  {len(steps)} steps captured")

    # Check that tool calls were captured
    tool_names = [s["tool_name"] for s in steps]
    print(f"  🔧  Tools used: {', '.join(tool_names)}")

    check("search_flights was called", "search_flights" in tool_names)
    check("search_hotels was called", "search_hotels" in tool_names)
    check("get_weather was called", "get_weather" in tool_names)

    # Check step quality
    has_latency  = all(s.get("latency_ms") is not None for s in steps)
    has_success  = all(s.get("success") is not None for s in steps)
    all_success  = all(s.get("success") for s in steps)

    check("All steps have latency_ms", has_latency)
    check("All steps have success flag", has_success)
    check("All tool calls succeeded", all_success)

    # Check reasoning extraction
    steps_with_reasoning = [s for s in steps if s.get("reasoning")]
    print(f"  💭  {len(steps_with_reasoning)}/{len(steps)} steps have extracted reasoning")

    # Check job was pushed
    try:
        job = api_get(f"/jobs/{ep_id}/status")
        check("Job was pushed to merger queue", job is not None)
        print(f"  📦  Job status: {job.get('status', 'unknown')}")
    except Exception:
        check("Job was pushed to merger queue", False)

    # Check metrics updated
    metrics = api_get("/metrics")
    check("Metrics counter incremented", metrics["requests_total"] > 0)

print(f"\n{'=' * 60}")
print(f"Results: {PASS} passed, {FAIL} failed")
print(f"{'=' * 60}")

if FAIL > 0:
    print("\n⚠️  Some checks failed — review above.")
    exit(1)
else:
    print("\n🎉 Real agent test PASSED! AGeval correctly evaluates a live LangGraph agent.\n")
