# AGeval

**Is your agent getting better or worse?**

AGeval is an episodic evaluation framework for LLM agents with persistent evaluation memory. One line of code gives you full observability: every tool call traced, every run scored, every episode searchable — and a four-layer memory system that learns from every run. Go from zero to your first evaluated episode in under 5 minutes. Works with any agent framework.

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
| "Which framework do I need to use?" | **Any framework** — LangGraph, OpenAI, CrewAI, AutoGen, Anthropic, MCP, or fully custom |
| "Is this failure new or recurring?" | **Failure-pattern memory** — signatures cluster known failure modes |
| "How does this run compare to peers?" | **Peer-relative scoring** — percentile bands within semantic cluster |

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

## Quick Start — 4 Ways to Integrate

### 1. Any Agent (Universal — works with everything)

```python
from ageval import AgentSession

with AgentSession(agent_id="my_agent_v1", task="book a flight to Paris") as session:
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

### Zero-Code Auto-Instrumentation

```python
import ageval.auto  # patches OpenAI + Anthropic clients globally — no other changes needed
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

Three complementary scorers run automatically after every episode.

### Rule-based scorer (`eval/rules.py`)
Deterministic, no LLM required:

| Metric | What it measures |
|---|---|
| `success_rate` | Fraction of tool calls that succeeded |
| `recovery_rate` | Fraction of env_errors followed by a successful step |
| `reasoning_coverage` | Fraction of steps with reasoning provided |
| `efficiency_score` | Penalises back-to-back duplicate tool calls |

### LLM judge (`eval/llm_judge.py`)
Configurable model (default: `gpt-4o-mini`, override with `AGEVAL_JUDGE_MODEL`):

| Dimension | Weight | What it measures |
|---|---|---|
| `task_completion` | 0.20 | Did the agent achieve the stated goal? |
| `hallucination_free` | 0.17 | Did the agent avoid facts not grounded in tool outputs? |
| `output_quality` | 0.13 | Is the final output useful and accurate? |
| `reasoning_quality` | 0.12 | Was the chain-of-thought coherent? |
| `instruction_following` | 0.12 | Did the agent stay within user's stated constraints? |
| `error_handling` | 0.10 | Did the agent recover gracefully? |
| `efficiency` | 0.08 | Did the agent avoid unnecessary steps? |
| `tool_appropriateness` | 0.08 | Were the right tools used? |

### 19 built-in deterministic metrics (no LLM required)

AGeval ships 19 auto-computed metrics, persisted as the `custom` scorer after every episode:

**Reliability:** `agent_error_rate`, `fatal_error_rate`, `first_call_success`, `last_call_success`

**Efficiency:** `step_economy`, `p95_step_latency`, `retry_overhead`, `backtrack_rate`, `token_economy`

**Agentic:** `tool_call_precision`, `goal_progress`, `reasoning_depth`, `reasoning_action_alignment`

**Observability:** `tool_diversity`, `multi_tool_usage`, `output_richness`

List them via `GET /metrics/catalogue` or `ageval.list_metrics()`.

### Optional advanced scorers

| Scorer | Description | Endpoint |
|---|---|---|
| `trajectory` | Edit-distance adherence to golden tool path | Built into merger |
| `pairwise` | LLM comparative judgment between two episodes | `GET /compare` |
| `reference` | RAG-grounded faithfulness + relevance scoring | `POST /episodes/{id}/score/reference` |

### Custom metrics

```python
from ageval import register_metric

@register_metric("cost_efficiency", weight=0.3)
def cost_efficiency(steps, episode):
    prices = [s["tool_output"].get("price", 999) for s in steps if s.get("success")]
    return 1.0 if min(prices, default=999) < 500 else 0.5
```

---

## Evaluation Memory

AGeval builds four memory layers across every episode your agents run. Each layer compounds value over time.

### Layer 1 — Failure-Pattern Memory
Clusters failed steps by `(error_category, tool_name, position_band, error_embedding)` into named signatures. New episodes are triaged against known failure patterns — you see "this failure appeared in 14 runs over 3 days" before you even open a trace.

### Layer 2 — Semantic Cluster Baselines (Peer-Relative Scoring)
Embeds every episode by task and groups them with K-means. Maintains running score distributions (mean, p10, p50, p90, stddev) per cluster. Every `GET /episodes/{id}` response includes a `percentile` and `band` ("bottom 10%", "typical", "top 10%") relative to that agent's peer group. Cold-start safe: falls back to absolute scores below n=20.

### Layer 3 — Procedural Memory (Golden Trajectories)
Mines the highest-scoring episodes per cluster to extract canonical tool sequences and expected step counts. Enables `trajectory_adherence` scoring — catches agents that reach the right answer via a wasteful or fragile path.

### Layer 4 — Regression & Drift Detection
Compares the last 7 days of runs vs the prior 7-day baseline per metric, per scorer, per agent. Surfaces score deltas, new failure signatures, step-count drift, and trajectory shape changes. Online drift alerts fire when a cluster's recent mean drops more than k·σ below baseline (configurable).

---

## Dashboard

The Next.js frontend has 17 pages covering every aspect of agent evaluation.

### Overview & Traces

| Page | Description |
|---|---|
| `/` | Landing page — animated episode replay, memory feature showcase, framework coverage |
| `/dashboard` | KPI aggregate — outcomes, avg scores, metric breakdown |
| `/traces` | Full episode list with real-time search (ID / task / agent) and outcome filter |
| `/episodes/[id]` | Single episode — steps timeline, reasoning, tool inputs/outputs, all scorer breakdowns |

### Evaluation Memory

| Page | Description |
|---|---|
| `/clusters` | Task semantic clusters with drift indicators |
| `/failures` | Failure-pattern signatures — recurrence counts, first/last seen, triage view |
| `/regression` | Score trajectory across versions — per-metric delta vs baseline |

### Evaluation Tools

| Page | Description |
|---|---|
| `/compare` | A/B episode comparison — trajectory LCS diff + LLM pairwise judgment |
| `/recall` | Semantic similarity search by task (pgvector) |
| `/datasets` | Golden datasets (Supabase-backed, user-scoped test cases) |
| `/red-teaming` | Adversarial probe runner |
| `/test-suites` | Test case collections |
| `/playground` | Live scoring sandbox |

### Settings & Admin

| Page | Description |
|---|---|
| `/settings` | Self-service API key generation, rotation, and revocation |
| `/team` | Multi-user management |

---

## API Endpoints

### Ingestion (SDK → Server)
```
POST /episodes            — create a stub episode
POST /steps               — write one step
POST /steps/batch         — write multiple steps
POST /jobs                — trigger scoring
POST /webhooks            — register webhook for score alerts
```

### Query (Dashboard / CLI)
```
GET  /overview                          — KPI aggregate: outcomes, avg score, metric breakdown
GET  /episodes                          — list episodes (filter: ?agent_id= &outcome=)
GET  /episodes/{id}                     — full detail + steps + scores + relative_scores
GET  /episodes/{id}/steps               — paginated steps
GET  /agents                            — distinct agent_ids for the authenticated user
GET  /trends?agent_id=X                 — score time-series (scorer = rules | custom | llm_judge)
GET  /metrics/catalogue                 — list all 19 built-in deterministic metrics + descriptions
GET  /similar?episode_id=X              — find similar episodes (pgvector)
GET  /recall?task=...                   — semantic search by task text
GET  /compare?episode_a=X&episode_b=Y   — trajectory diff + pairwise judgment
GET  /jobs/{id}/status                  — poll merge/scoring job status
GET  /health                            — liveness probe
GET  /metrics                           — operational metrics (requests, latencies)
```

### Evaluation Memory
```
GET  /clusters                          — list semantic task clusters
GET  /drift                             — drifting clusters (recent mean vs baseline)
GET  /drift/alerts                      — online drift alert feed
GET  /clusters/{id}/failures            — failure aggregate for a cluster
GET  /agents/{id}/regression            — regression report (score deltas, new failures, drift)
POST /episodes/{id}/score/reference     — RAG-grounded faithfulness + relevance scoring
```

### Evaluation Services
```
POST /redteam/run                       — run adversarial probes, get a security scorecard
POST /synthetic/generate                — LLM-bootstrap a dataset from seed examples
GET  /v1/datasets?project_id=X          — list golden datasets
POST /v1/datasets                       — create a golden dataset + test cases
```

### Key Management
```
POST /register          — create API key (admin only)
POST /keys              — self-service key generation
POST /keys/rotate       — rotate your key
GET  /keys              — list your keys
DELETE /keys/{id}       — revoke a key
```

All requests require `Authorization: Bearer <token>`. Dashboard users send a Supabase JWT; SDK agents send `ageval-sk-<48-hex-chars>`.

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
| **Any framework (zero-code)** | `import ageval.auto` | Zero changes |

---

## Run the Server

```bash
# Required:
AGEVAL_SUPABASE_URL=...
AGEVAL_SUPABASE_SERVICE_KEY=...
AGEVAL_ADMIN_SECRET=...         # required — no default

# Optional:
OPENAI_API_KEY=...              # for embeddings + LLM judge
AGEVAL_JUDGE_MODEL=gpt-4o-mini  # override the LLM judge model
LANGSMITH_API_KEY=...           # only for LangChain agents
REDIS_URL=...                   # for distributed rate limiting (falls back to in-memory)

# Start:
uvicorn main:app --reload

# Start the background merger worker (scoring + clustering + memory):
python -m merger.worker
```

---

## Background Worker

The merger worker (`python -m merger.worker`) runs the full evaluation pipeline for each episode:

1. Polls `episode_jobs` for pending work (Supabase `SELECT FOR UPDATE SKIP LOCKED` — no Redis required)
2. Scores the episode: rules + LLM judge + 19 deterministic metrics
3. Embeds the task and groups into semantic clusters (K-means, every ~5 min)
4. Updates cluster score baselines for peer-relative scoring
5. Folds failing steps into failure-pattern memory
6. Mines golden trajectories from top-scoring episodes
7. Runs regression comparison (last 7d vs prior 7d baseline)
8. Fires drift alerts when cluster performance degrades
9. Delivers webhooks for low-score or anomaly events

**Graceful degradation:** missing scikit-learn → clustering skipped; missing OpenAI key → embeddings and LLM judge skipped; everything else continues.

---

## Auth

Two credential types:

| Type | Credential | Use case |
|---|---|---|
| **Dashboard user** | Supabase JWT (email + password login) | Web UI access |
| **SDK agent** | `ageval-sk-<48-hex-chars>` API key | SDK ingestion + API calls |

API keys are stored as SHA-256 hashes. Generate and manage them at `/settings` in the dashboard or via `POST /keys`.

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

Test coverage includes: SDK tracers, AgentSession API, API contracts, key management, evaluation memory (Phase 1–3), metrics, datasets, failure memory, red-team/synthetic generation, rate limiting, and edge cases.

---

## Security

- API keys stored as SHA-256 hashes — raw key never stored
- SSRF protection on webhook URLs (registration + DNS re-check at delivery time)
- Row Level Security (RLS) at Postgres layer — multi-tenant isolation
- HMAC-SHA256 webhook signatures
- Registration disabled unless `AGEVAL_ADMIN_SECRET` is explicitly set
- Rate limiting (Redis or in-memory) per API key
- OpenTelemetry span export for production observability

---

## License

MIT
