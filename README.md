# AGeval

**Is your agent getting better or worse?**

AGeval is an episodic evaluation framework for LLM agents with persistent evaluation memory. One import gives you full observability: every tool call traced, every run scored, and a four-layer memory system that learns from every episode. Works with any agent framework — including LangGraph, CrewAI, AutoGen, MCP, OpenAI, and Anthropic. Go from zero to your first evaluated episode in under 5 minutes.

[![CI](https://github.com/Jeel3011/AGeval/actions/workflows/ci.yml/badge.svg)](https://github.com/Jeel3011/AGeval/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Why AGeval?

| Problem | AGeval Solution |
|---------|----------------|
| "Is my agent getting better or worse?" | **28 built-in metrics** + 3 independent scorers — every run gets a reliability number |
| "What happened in that failed run?" | **Full trace** — every tool call, input, output, latency, reasoning |
| "Has my agent seen a task like this before?" | **Episodic memory** — pgvector similarity search across all past runs |
| "Is this failure new or recurring?" | **Failure-pattern memory** — signatures cluster known failure modes and track recurrence |
| "How does this run compare to peers?" | **Peer-relative scoring** — percentile bands within semantic cluster |
| "Which framework do I need to use?" | **Any framework** — LangGraph, OpenAI, CrewAI, AutoGen, Anthropic, MCP, or fully custom |
| "I can't change my agent code" | **Zero-code auto-instrumentation** — `import ageval.auto` patches everything globally |

---

## Install

```bash
pip install ageval-sdk

# With framework-specific extras:
pip install ageval-sdk[openai]      # For OpenAI function-calling agents
pip install ageval-sdk[langchain]   # For LangGraph / LangChain agents
pip install ageval-sdk[anthropic]   # For Anthropic (Claude) agents
pip install ageval-sdk[otel]        # For OpenTelemetry export
pip install ageval-sdk[all]         # Everything
```

---

## Quick Start — 5 Ways to Integrate

### 1. Zero-Code Auto-Instrumentation

```python
import ageval.auto  # patches OpenAI + Anthropic SDKs and LangChain callbacks globally
                    # idempotent, framework-agnostic, silent no-op if AGEVAL_API_KEY is unset
```

### 2. Any Agent (Universal)

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
    # Or auto-wrap any callable:
    hotels = session.traced(search_hotels, reasoning="Finding hotels")("Paris", budget="moderate")
```

### 3. OpenAI Function Calling

```python
from ageval import trace_openai
from openai import OpenAI

result = trace_openai(
    client=OpenAI(),
    messages=[{"role": "user", "content": "Plan a trip to Paris"}],
    tools=my_tool_definitions,
    tool_functions={"search_flights": search_flights, "search_hotels": search_hotels},
    agent_id="trip_planner_v1",
    task="Plan a trip to Paris",
)
# result["episode_id"] → query scores later
```

### 4. Anthropic (Claude) Tool Use

```python
from ageval import trace_anthropic
from anthropic import Anthropic

result = trace_anthropic(
    client=Anthropic(),
    messages=[{"role": "user", "content": "Plan a trip to Paris"}],
    tools=my_tool_definitions,           # Anthropic format (name/description/input_schema)
    tool_functions={"search_flights": search_flights, "search_hotels": search_hotels},
    agent_id="trip_planner_v1",
    task="Plan a trip to Paris",
    model="claude-haiku-4-5-20251001",
)
# result["episode_id"], result["usage"] → tokens captured for cost metrics
```

### 5. LangGraph / LangChain (Zero Changes)

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

Three independent scorers run automatically after every episode.

### Rule-based scorer (`eval/rules.py`)
Deterministic, always available, no LLM required:

| Metric | Weight | What it measures |
|---|---|---|
| `success_rate` | 0.25 | Fraction of tool calls that succeeded |
| `recovery_rate` | 0.25 | Env errors followed by a successful step |
| `reasoning_coverage` | 0.25 | Steps with reasoning provided |
| `efficiency_score` | 0.25 | Penalises back-to-back duplicate tool calls |

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
| `tool_appropriateness` | 0.08 | Were the right tools used for each sub-task? |

### 28 built-in deterministic metrics (no LLM required)

All 28 auto-computed metrics are persisted as the `custom` scorer after every episode. List them via `GET /metrics/catalogue` or `ageval.list_metrics()`.

**Reliability**
| Metric | What it measures |
|---|---|
| `agent_error_rate` | Fraction of steps failing due to agent mistakes |
| `env_error_rate` | Fraction failing due to environment / transient errors |
| `fatal_error_rate` | Fraction of failures that are non-recoverable |
| `first_call_success` | Success on the first tool call (upfront understanding) |
| `last_call_success` | Final step succeeded (clean landing) |

**Efficiency**
| Metric | What it measures |
|---|---|
| `step_economy` | Penalises long episodes (1.0 at ≤3 steps, 0.0 at ≥20) |
| `p95_step_latency` | Per-call responsiveness (1.0 at ≤1s, 0.0 at ≥15s) |
| `retry_overhead` | Fraction of steps that repeat the same tool/input after failure |

**Agentic Behaviour**
| Metric | What it measures |
|---|---|
| `tool_call_precision` | Successful unique-purpose tool calls / total calls |
| `goal_progress` | Forward momentum — fraction of transitions to new tools |
| `reasoning_depth` | Average reasoning string length (chain-of-thought quality) |

**Cost & Backtracking**
| Metric | What it measures |
|---|---|
| `backtrack_rate` | Repeated `(tool, input)` pairs anywhere in trajectory |
| `token_economy` | Token efficiency (1.0 at ≤2k tokens, 0.0 at ≥50k) |
| `reasoning_action_alignment` | Tool calls preceded by reasoning AND succeeded |

**Observability**
| Metric | What it measures |
|---|---|
| `tool_diversity` | Unique tools used / total steps |
| `multi_tool_usage` | Binary: agent used 2+ distinct tools |
| `output_richness` | Information density of tool outputs (avg JSON length) |
| `latency_budget` | Decays from 1.0 at 5s to 0.0 at 60s total episode time |
| `error_recovery_speed` | Steps to recover from an env_error |

**Deep Evaluation v2**
| Metric | What it measures |
|---|---|
| `recovery_success_rate` | Steps after failure that ultimately succeed |
| `failure_clustering` | Failures grouped or isolated (1.0 = isolated blips) |
| `tool_selection_entropy` | Balanced exploration across tools (normalized Shannon entropy) |
| `progress_monotonicity` | No rework on already-solved sub-tasks |
| `cost_per_success` | Tokens per successful step (1.0 at ≤1k, 0.0 at ≥20k) |
| `latency_consistency` | Stability of per-step timing (1 − coefficient of variation) |
| `error_concentration` | Errors in one tool (diagnosable) vs spread (systemic) |

### Optional advanced scorers

| Scorer | Description |
|---|---|
| `trajectory` | Edit-distance adherence to the golden tool path mined per task cluster |
| `pairwise` | LCS trajectory diff + LLM comparative judgment between two episodes |
| `reference` | RAG-grounded faithfulness and answer relevance scoring (`POST /episodes/{id}/score/reference`) |

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

AGeval builds four memory layers across every episode. Each layer compounds value over time.

### Layer 1 — Failure-Pattern Memory
Clusters failed steps by `(error_category, tool_name, position_band, error_embedding)` into named signatures. New episodes are triaged against known failure patterns — you see "this failure appeared in 14 runs over 3 days" before opening a single trace. Signatures seed auto-generated regression evals.

### Layer 2 — Semantic Cluster Baselines (Peer-Relative Scoring)
Embeds every episode by task and groups with K-means. Maintains running score distributions (mean, p10, p50, p90, stddev) per cluster. Every `GET /episodes/{id}` response includes a `percentile` and band (`"bottom 10%"`, `"typical"`, `"top 10%"`) relative to the agent's peer group. Cold-start safe: falls back to absolute scores below n=20.

### Layer 3 — Procedural Memory (Golden Trajectories)
Mines the highest-scoring episodes per cluster to extract canonical tool sequences and expected step counts. Enables `trajectory_adherence` scoring — catches agents that reach the right answer via a wasteful or fragile path.

### Layer 4 — Regression & Drift Detection
Compares the last 7 days of runs vs the prior 7-day baseline per metric, per scorer, per agent. Surfaces score deltas, new failure signatures, step-count drift, and trajectory shape changes. Online drift alerts fire when a cluster's recent mean drops more than k·σ below baseline (`DRIFT_K=2.0` by default).

---

## BudgetGuard

A hard-cap spend proxy for Anthropic that protects against runaway costs:

```python
from examples.agents.budget_guard import BudgetGuard
from anthropic import Anthropic

guarded = BudgetGuard(Anthropic(), cap_usd=0.50)
# Works like the native client — raises BudgetExceeded before hitting the API
# if the worst-case cost of the call would breach the cap.
response = guarded.messages.create(model="claude-haiku-4-5-20251001", ...)
```

`BudgetGuard` pre-estimates cost using a token-counter + `max_tokens` assumption and reconciles with actual `usage` after each call. Pricing table covers Haiku, Sonnet, and Opus.

---

## Example Agents (22 reference implementations)

All examples live in `examples/agents/` and share a common toolkit (`toolkit.py`) with 20+ realistic production tools — HTTP, SQL, vector search, payments, file I/O, code execution, calendar, Slack, and more.

| # | Agent | Framework | What it demonstrates |
|---|-------|-----------|----------------------|
| 01 | Customer Support Agent | OpenAI | `get_customer`, `vector_search`, `sql_query`, `create_ticket`, `send_email` — tier-1 support with knowledge-base lookup and ticket escalation |
| 02 | E-commerce Order Agent | OpenAI | Multi-step order processing — product lookup, inventory check, payment flow |
| 03 | Travel Concierge Agent | OpenAI | `get_weather`, `search_flights`, `currency_convert`, `book_calendar` — cross-tool data flow |
| 04 | DevOps Incident Agent | OpenAI | Infrastructure incident response — health checks, alerting, mitigation |
| 05 | Financial Analyst Agent | OpenAI | Market analysis and structured reporting |
| 06 | Research Assistant | Anthropic | Knowledge synthesis from multiple sources |
| 07 | Sales Outreach Agent | Anthropic | `sql_query` → `get_customer` → `send_email` → `book_calendar` — full outreach pipeline |
| 08 | Coding Agent | Anthropic | `write_file`, `read_file`, `run_python` — write function, save, execute in sandbox |
| 09 | LangGraph Support Router | LangGraph | Real `StateGraph` with tool node — traces MCP-served tools via `AgentSession` |
| 10 | LangGraph Data Pipeline | LangGraph | Multi-step ETL workflow |
| 11 | LangGraph Human-in-Loop | LangGraph | Agent with approval gate checkpoints |
| 12 | CrewAI Marketing Crew | CrewAI | Two-agent crew (Researcher + Copywriter) generating launch copy |
| 13 | CrewAI Recruiting Crew | CrewAI | Multi-agent recruitment process |
| 14 | MCP Server Agent | MCP | Real MCP server/client transport — proves AGeval traces MCP tool calls |
| 15 | MCP + Anthropic Agent | MCP + Anthropic | Anthropic client calling an MCP server |
| 16 | AutoGen Group Chat | AutoGen | Multi-agent group conversation |
| 17 | RPA Back Office Agent | Custom | File processing and form-filling — robotic process automation |
| 18 | LangGraph Long Research | LangGraph | 15–25 tool calls — stresses step volume and aggregation |
| 19 | LangGraph Supervisor Team | LangGraph | Supervisor-routed multi-agent team |
| 20 | Failing Retry Loop (intentional) | LangGraph | `reconcile_inventory` always fails — demonstrates failure detection for stuck retry loops |
| 21 | Bad Arguments (intentional) | LangGraph | Argument validation failures — shows `agent_error` vs `env_error` classification |
| 22 | BudgetGuard | Anthropic | Hard USD spend cap with worst-case cost estimation |

Run all examples:

```bash
python examples/agents/run_all.py
```

---

## Supported Frameworks

| Framework | Integration | Effort |
|-----------|-------------|--------|
| **Any custom agent** | `AgentSession` + `record_step()` | Wrap each tool call |
| **OpenAI function calling** | `trace_openai()` — full tool loop | One function call |
| **Anthropic (Claude) tool use** | `trace_anthropic()` — full tool loop | One function call |
| **LangGraph / LangChain** | `trace_agent()` — StateGraph drop-in | Zero changes |
| **CrewAI** | `AgentSession` + `traced()` (via LangChain) | Wrap each tool call |
| **AutoGen** | `AgentSession` + `traced()` (via OpenAI/Anthropic) | Wrap each tool call |
| **MCP servers** | `AgentSession` + `record_step()` | Wrap MCP tool calls |
| **Any framework (zero-code)** | `import ageval.auto` | Zero changes |

---

## Dashboard

The Next.js 14 frontend has 17 pages.

### Overview & Traces

| Page | Description |
|---|---|
| `/` | Landing page — animated episode replay hero, 4-layer memory explainer, 6-framework coverage |
| `/dashboard` | KPI aggregate — outcomes, avg scores per scorer, failure rate, latency |
| `/traces` | Full episode list with real-time search (ID / task / agent ID) and outcome filter |
| `/episodes/[id]` | Single episode — step timeline, reasoning, tool inputs/outputs, all scorer breakdowns |

### Evaluation Memory

| Page | Description |
|---|---|
| `/clusters` | Semantic task clusters with drift indicators |
| `/failures` | Failure-pattern signatures — recurrence counts, first/last seen, triage view |
| `/regression` | Score trajectory across versions — per-metric delta vs baseline |

### Evaluation Tools

| Page | Description |
|---|---|
| `/compare` | A/B episode comparison — LCS trajectory diff + LLM pairwise verdict |
| `/recall` | Semantic similarity search across all past runs (pgvector) |
| `/datasets` | Golden dataset management — Supabase-backed, user-scoped test cases |
| `/red-teaming` | Adversarial probe runner — prompt injection, data exfiltration, jailbreak |
| `/test-suites` | Test suite collections |
| `/playground` | Live scoring sandbox |

### Admin

| Page | Description |
|---|---|
| `/settings` | Self-service API key generation, rotation, and revocation |
| `/team` | Multi-user management |

---

## API Reference

### Ingestion (SDK → Server)
```
POST /episodes            — create a stub episode
POST /steps               — write one step
POST /steps/batch         — write multiple steps in one request
POST /jobs                — trigger scoring for a completed episode
POST /webhooks            — register a webhook for score / anomaly alerts
```

### Query
```
GET  /overview                          — KPI aggregate: outcomes, avg score, metric breakdown
GET  /episodes                          — list episodes (filter: ?agent_id= &outcome=)
GET  /episodes/{id}                     — full detail + steps + scores + relative_scores
GET  /episodes/{id}/steps               — paginated steps
GET  /agents                            — distinct agent_ids for the authenticated user
GET  /trends?agent_id=X                 — score time-series (scorer = rules | custom | llm_judge)
GET  /metrics/catalogue                 — list all 28 built-in metrics + descriptions
GET  /similar?episode_id=X              — find similar episodes (pgvector kNN)
GET  /recall?task=...                   — semantic search by free-text task
GET  /compare?episode_a=X&episode_b=Y   — trajectory diff + pairwise judgment
GET  /jobs/{id}/status                  — poll merge/scoring job
GET  /health                            — liveness probe
GET  /metrics                           — operational metrics (requests, latencies)
```

### Evaluation Memory
```
GET  /clusters                          — list semantic task clusters
GET  /drift                             — clusters whose recent mean is drifting below baseline
GET  /drift/alerts                      — online drift alert feed
GET  /clusters/{id}/failures            — failure pattern aggregate for a cluster
GET  /agents/{id}/regression            — regression report (score deltas, new failure signatures, drift)
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
POST /register          — create API key (admin only, requires AGEVAL_ADMIN_SECRET)
POST /keys              — self-service key generation
POST /keys/rotate       — rotate your key
GET  /keys              — list your keys
DELETE /keys/{id}       — revoke a key
```

All requests require `Authorization: Bearer <token>`. Dashboard users send a Supabase JWT (email + password login at `/login`). SDK agents send an `ageval-sk-<48-hex-chars>` key generated at `/settings`.

---

## Run the Server

```bash
# Required:
AGEVAL_SUPABASE_URL=...
AGEVAL_SUPABASE_SERVICE_KEY=...
AGEVAL_ADMIN_SECRET=...            # no default — registration disabled without this

# Optional:
OPENAI_API_KEY=...                 # for pgvector embeddings + LLM judge
AGEVAL_JUDGE_MODEL=gpt-4o-mini     # override the LLM judge model
LANGSMITH_API_KEY=...              # only for LangChain / LangGraph agents
REDIS_URL=...                      # distributed rate limiting (falls back to in-memory)
DRIFT_K=2.0                        # drift alert sensitivity (std devs below baseline)
RECENT_DAYS=7                      # lookback window for regression + drift
POLL_INTERVAL=5                    # merger worker poll interval in seconds

# Start the API:
uvicorn main:app --reload

# Start the background merger worker:
python -m merger.worker

# Or with Docker:
docker-compose up
```

---

## Background Worker

The merger worker (`python -m merger.worker`) runs the full evaluation pipeline:

1. Polls `episode_jobs` via Supabase `SELECT FOR UPDATE SKIP LOCKED` — no Redis needed, scales to many workers
2. Derives outcome, latency, total_steps, and `episode_fingerprint` (stable hash of tool sequence + outcome)
3. Runs all three scorers: rules + LLM judge + 28 deterministic metrics
4. Embeds tasks and clusters episodes with K-means (~every 5 min, configurable)
5. Updates cluster score baselines for peer-relative scoring
6. Folds failing steps into failure-pattern memory
7. Mines golden trajectories from top-scoring episodes per cluster
8. Runs regression comparison (last 7d vs prior 7d baseline per scorer and metric)
9. Fires drift alerts when a cluster's recent mean drops k·σ below baseline
10. Delivers webhooks for low-score or anomaly events (with HMAC-SHA256 signatures and retries)

**Graceful degradation:** missing scikit-learn → clustering skipped; missing OpenAI key → embeddings and LLM judge skipped; everything else continues.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

| Test file | Covers |
|---|---|
| `test_session.py` | `AgentSession`, `trace_callable` |
| `test_tracers.py` | `trace_agent`, `trace_openai`, `trace_anthropic` |
| `test_auto_instrumentation.py` | Monkeypatching OpenAI / Anthropic / LangChain globally |
| `test_metrics.py` | All 28 built-in metrics + custom metric registry |
| `test_property_metrics.py` | Property-based metric testing (hypothesis) |
| `test_property_tracers.py` | Property tests for tracer logic |
| `test_eval_rules.py` | Rule-based scorer |
| `test_eval_memory.py` | Memory system integration |
| `test_phase2_memory.py` | Regression detection, procedural memory |
| `test_phase3_eval.py` | Pairwise, drift alerts, reference-grounded scoring |
| `test_langgraph_agents_live.py` | Live LangGraph integration |
| `test_edge_cases.py` | Error conditions, malformed inputs |
| `test_api_contract.py` | API schema validation |
| `test_sdk.py` | SDK integration |
| `test_datasets_router.py` | Dataset API endpoints |
| `test_failures_router.py` | Failure analysis endpoints |
| `test_redteam_synthetic.py` | Red-team + synthetic data generation |
| `test_rate_limiter.py` | Rate limiting |
| `test_key_management.py` | API key gen / rotate / revoke |

---

## Graceful Degradation

If `AGEVAL_API_KEY` is not set:
- `trace_agent()` falls back to plain `agent.invoke()`
- `trace_openai()` falls back to plain `chat.completions.create()`
- `trace_anthropic()` falls back to plain `messages.create()`
- `import ageval.auto` patches silently no-op
- `AgentSession` records steps locally but doesn't send them
- **Zero crashes, zero overhead, zero exceptions**

---

## Security

- API keys stored as SHA-256 hashes — raw key never persisted
- SSRF protection on webhook URLs at registration and delivery time (DNS re-check)
- Row Level Security (RLS) at Postgres layer — complete multi-tenant isolation
- HMAC-SHA256 webhook signatures
- Registration disabled unless `AGEVAL_ADMIN_SECRET` is explicitly set
- Per-key rate limiting (Redis or in-memory fallback)
- OpenTelemetry span export for production observability

---

## License

MIT
