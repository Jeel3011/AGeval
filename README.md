# AGeval

**Is your agent getting better or worse?**

AGeval is an episodic evaluation framework for LLM agents. With just one line of code, you get full observability: every tool call traced, every run scored, and every episode searchable. Go from zero to your first evaluated episode in under 5 minutes. Works with any agent framework.

[![CI](https://github.com/Jeel3011/AGeval/actions/workflows/ci.yml/badge.svg)](https://github.com/Jeel3011/AGeval/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Why AGeval?

| Problem | AGeval Solution |
|---------|----------------|
| "Is my agent getting better or worse?" | **Automatic scoring** — every run gets a reliability number |
| "What happened in that failed run?" | **Full trace** — every tool call, input, output, latency, reasoning |
| "Has my agent seen a task like this before?" | **Episodic memory** — pgvector similarity search across all past runs |
| "Which framework do I need to use?" | **Any framework** — LangGraph, OpenAI, CrewAI, AutoGen, or fully custom |

---

## Install

```bash
pip install ageval-sdk

# With framework-specific extras:
pip install ageval-sdk[openai]      # For OpenAI function-calling agents
pip install ageval-sdk[langchain]   # For LangGraph / LangChain agents
pip install ageval-sdk[all]         # Everything
```

---

## Quick Start — 3 Ways to Integrate

### 1. Any Agent (Universal — works with everything)

```python
from ageval import AgentSession

with AgentSession(agent_id="my_agent_v1", task="book a flight to Paris") as session:
    # Your agent does its thing — any framework, any language model
    result = search_flights("Paris")
    session.record_step(
        tool_name="search_flights",
        tool_input={"destination": "Paris"},
        tool_output=result,
        success=True,
        reasoning="User wants to go to Paris",
        latency_ms=120,
    )

    # Or wrap functions for automatic tracing:
    traced_hotels = session.traced(search_hotels, reasoning="Finding hotels")
    hotels = traced_hotels("Paris", budget="moderate")
```

### 2. OpenAI Function Calling

```python
from ageval import trace_openai
from openai import OpenAI

client = OpenAI()
result = trace_openai(
    client=client,
    messages=[{"role": "user", "content": "Plan a trip to Paris"}],
    tools=my_tool_definitions,
    tool_functions={"search_flights": search_flights, "search_hotels": search_hotels},
    agent_id="trip_planner_v1",
    task="Plan a trip to Paris",
)
# result["episode_id"] → use to query scores later
```

### 3. Anthropic (Claude) Tool Use

```python
from ageval import trace_anthropic
from anthropic import Anthropic

client = Anthropic()
result = trace_anthropic(
    client=client,
    messages=[{"role": "user", "content": "Plan a trip to Paris"}],
    tools=my_tool_definitions,           # Anthropic format (name/description/input_schema)
    tool_functions={"search_flights": search_flights, "search_hotels": search_hotels},
    agent_id="trip_planner_v1",
    task="Plan a trip to Paris",
    model="claude-haiku-4-5-20251001",
)
# result["episode_id"], result["usage"] → tokens captured for cost metrics
```

### 4. LangGraph / LangChain (Zero Changes)

```python
from ageval import trace_agent

result = trace_agent(
    agent    = your_langgraph_app,
    input    = {"messages": [("user", "Plan a trip to Paris")]},
    agent_id = "trip_planner_v1",
    task     = "Plan a trip to Paris",
)
```

---

## What Gets Captured

For every tool call your agent makes:

| Field | What it means |
|---|---|
| `tool_name` | Which tool was called |
| `tool_input` | What was passed in (any JSON) |
| `tool_output` | What came back (any JSON) |
| `success` | Did it work |
| `error_category` | `agent_error` / `env_error` / `unknown` |
| `is_recoverable` | Should the agent retry |
| `reasoning` | Why the agent made this call |
| `latency_ms` | How long it took |

---

## Scoring

Two complementary scorers run automatically after every episode:

### Rule-based scorer (`eval/rules.py`)
Deterministic, no LLM required:

| Metric | What it measures |
|---|---|
| `success_rate` | Fraction of tool calls that succeeded |
| `recovery_rate` | Fraction of env_errors followed by a successful step |
| `reasoning_coverage` | Fraction of steps with reasoning provided |
| `efficiency_score` | Penalises back-to-back duplicate tool calls |

### LLM judge (`eval/llm_judge.py`)
Uses GPT-4o-mini (or any model) for qualitative evaluation:

| Metric | What it measures |
|---|---|
| `task_completion` | Did the agent achieve the stated goal? |
| `reasoning_quality` | Was the chain-of-thought coherent? |
| `error_handling` | Did the agent recover gracefully? |
| `output_quality` | Is the final output useful and accurate? |
| `hallucination_free` | Did the agent avoid stating facts not grounded in its tool outputs? |
| `instruction_following` | Did the agent stay within the user's stated constraints? |

### Built-in deterministic metrics (19, no LLM required)

Beyond the 4 rule metrics above, AGeval ships 19 registered deterministic
metrics — reliability (`agent_error_rate`, `fatal_error_rate`, `first/last_call_success`),
efficiency (`step_economy`, `p95_step_latency`, `retry_overhead`, `backtrack_rate`,
`token_economy`), agentic (`tool_call_precision`, `goal_progress`, `reasoning_depth`,
`reasoning_action_alignment`), and observability (`tool_diversity`, `multi_tool_usage`,
`output_richness`). The merger runs all of them after every episode and persists
the result as the `custom` scorer. List them via `GET /metrics/catalogue` or
`ageval.list_metrics()`.

### Custom metrics

Define your own domain-specific metrics:

```python
from ageval import register_metric

@register_metric("cost_efficiency", weight=0.3)
def cost_efficiency(steps, episode):
    """Did the agent pick the cheapest option?"""
    prices = [s["tool_output"].get("price", 999) for s in steps if s.get("success")]
    return 1.0 if min(prices, default=999) < 500 else 0.5
```

---

## Dashboard

Open `dashboard/index.html` in your browser — no build step required.

Features:
- **Episode list** with outcome badges and score bars
- **Step timeline** — click any step to see reasoning and tool output
- **Rule score + LLM judge score breakdown**
- **Compare** two episodes side-by-side
- **Recall** — find past runs similar to any task (semantic search)
- **Score trends** — track agent reliability over time (via `/trends` API)

---

## API Endpoints

### Ingestion (SDK → Server)
```
POST /episodes       — create a stub episode
POST /steps          — write one step
POST /steps/batch    — write multiple steps
POST /jobs           — trigger scoring
```

### Query (Dashboard / CLI)
```
GET  /overview                 — one-call KPI aggregate: outcomes, avg score per scorer, metric breakdown
GET  /episodes                 — list episodes (filter: ?agent_id= &outcome=)
GET  /episodes/{id}            — full detail + steps + scores
GET  /episodes/{id}/steps      — paginated steps
GET  /agents                   — distinct agent_ids for the authenticated user
GET  /trends?agent_id=X        — score time-series (scorer = rules | custom | llm_judge)
GET  /metrics/catalogue        — list all built-in deterministic metrics + descriptions
GET  /similar?episode_id=X     — find similar episodes
GET  /recall?task=...          — semantic search by task
GET  /compare?episode_a=X&episode_b=Y
```

### Evaluation services
```
POST /redteam/run              — run real adversarial probes against a model, get a security scorecard
POST /synthetic/generate       — LLM-bootstrap a dataset from seed examples
GET  /v1/datasets?project_id=X — list golden datasets (Supabase-backed, user-scoped)
POST /v1/datasets              — create a golden dataset + test cases
```

### Key Management
```
POST /register                 — create API key (admin only)
POST /keys/rotate              — rotate your key
GET  /keys                     — list your keys
DELETE /keys/{id}              — revoke a key
```

All requests require `Authorization: Bearer ageval-sk-<your-key>`.

---

## Supported Frameworks

| Framework | Integration | Effort |
|-----------|-------------|--------|
| **Any custom agent** | `AgentSession` + `record_step()` | Wrap each tool call |
| **OpenAI function calling** | `trace_openai()` — full loop | One function call |
| **Anthropic (Claude) tool use** | `trace_anthropic()` — full loop | One function call |
| **LangGraph / LangChain** | `trace_agent()` — drop-in | Zero changes |
| **CrewAI, AutoGen** | `AgentSession` + `traced()` | Wrap each tool call |
| **Any async agent** | `AgentSession` + `traced_async()` | Wrap each tool call |

---

## Run the Server

```bash
# Required:
AGEVAL_SUPABASE_URL=...
AGEVAL_SUPABASE_SERVICE_KEY=...
AGEVAL_ADMIN_SECRET=...        # required — no default

# Optional:
OPENAI_API_KEY=...             # for embeddings + LLM judge
LANGSMITH_API_KEY=...          # only for LangChain agents

# Start:
uvicorn main:app --reload

# Start the merger worker:
python -m merger.worker
```

---

## Graceful Degradation

If `AGEVAL_API_KEY` is not set:
- `trace_agent()` falls back to plain `agent.invoke()`
- `trace_openai()` falls back to plain `chat.completions.create()`
- `AgentSession` records steps locally but doesn't send them
- **Zero crashes, zero overhead, zero exceptions**

---

## Run Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Security

- API keys stored as SHA-256 hashes only — raw key never stored
- SSRF protection on webhook URLs (registration + delivery time DNS re-check)
- Row Level Security (RLS) at Postgres layer — multi-tenant isolation
- HMAC-SHA256 webhook signatures
- Registration disabled unless `AGEVAL_ADMIN_SECRET` is explicitly set
- Rate limiting (Redis or in-memory) per API key

---

## License

MIT