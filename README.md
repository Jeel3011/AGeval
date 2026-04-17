# ageval

Episodic evaluation framework for LLM agents.
Traces every tool call, scores agent behaviour, stores embeddings for similarity search.

---

## Supported Frameworks

| Framework | Integration path | Effort |
|-----------|-----------------|--------|
| **LangGraph / LangChain** | `trace_agent()` — one-line drop-in | Zero changes |
| **AutoGen, CrewAI, custom loops** | `EpisodeSession` + `@episodic_trace` | Wrap each tool call |
| **Any async agent** | `async_episodic_trace` decorator | Wrap each tool call |

> **Note:** The LangSmith dependency is fully optional. Pass `run_id="none"` to score using only your step data.

---

## Install

```bash
# from PyPI (once published)
pip install ageval

# or directly from GitHub
pip install git+https://github.com/Jeel3011/AGeval.git#subdirectory=ageval
```

---

## Setup — 2 steps

**Step 1 — Add one env var to your `.env`**

```bash
AGEVAL_API_KEY=ageval-sk-xxxxxxxxxxxxxxxx   # the ONLY thing you need
```

**Step 2 — Replace your `agent.invoke()` with `trace_agent()`**

Before:
```python
result = react_app.invoke({"messages": [question]})
```

After:
```python
from ageval import trace_agent

result = trace_agent(
    agent    = react_app,
    input    = {"messages": [question]},
    agent_id = "my_agent_v1",
    task     = question,
)
```

That's it. Every agent run is now:
- **Traced** — every tool call captured (input, output, latency, error category)
- **Scored** — success rate, recovery rate, reasoning coverage, efficiency
- **Judged** — LLM-as-judge evaluation of task completion and reasoning quality
- **Embedded** — pgvector for similarity search across episodes
- **Stored** in Supabase

---

## What gets captured automatically

For every tool call your agent makes:

| Field | What it means |
|---|---|
| `tool_name` | Which tool was called |
| `tool_input` | What was passed in (dict, str, list — any JSON) |
| `tool_output` | What came back (dict, str, list — any JSON) |
| `success` | Did it work |
| `error_category` | `agent_error` / `env_error` / `unknown` |
| `is_recoverable` | Should the agent retry |
| `reasoning` | Why the agent made this call (extracted from LLM output) |
| `latency_ms` | How long it took |

---

## Scoring

Two complementary scorers run automatically after every episode:

### Rule-based scorer (`eval/rules.py`)
Deterministic, no LLM required:

| Metric | What it measures |
|---|---|
| `success_rate` | Fraction of tool calls that succeeded |
| `recovery_rate` | Fraction of `env_errors` followed by a successful step |
| `reasoning_coverage` | Fraction of steps where the agent provided reasoning |
| `efficiency_score` | Penalises back-to-back duplicate tool calls |

### LLM judge (`eval/llm_judge.py`)
Uses GPT-4o-mini to evaluate (requires `OPENAI_API_KEY`).
The judge receives the full step trace **and** the final agent output for grounded scoring:

| Metric | What it measures |
|---|---|
| `task_completion` | Did the agent achieve the stated goal? |
| `reasoning_quality` | Was the chain-of-thought coherent? |
| `error_handling` | Did the agent recover gracefully from failures? |
| `output_quality` | Is the final output useful and accurate? |

Both scorers write to `episode_scores` with their respective `scorer` name.

---

## Dashboard

Open `dashboard/index.html` in your browser — no build step required.

Features:
- **Episode list** with outcome badges and score bars
- **Step timeline** — click any step to see reasoning and tool output
- **Rule score + LLM judge score breakdown**
- **Compare** two episodes side-by-side
- **Recall** — find past runs similar to any task (semantic search)

The dashboard asks for your API key on first load and stores it in `sessionStorage` only.

---

## Lower-level SDK (for fine-grained control — any framework)

```python
from sdk.episodic_sdk import EpisodeSession

with EpisodeSession(agent_id="my_agent", task="do something") as session:
    session.start()

    # Wrap each tool call manually
    traced_search = session.trace(search_fn, reasoning=llm_output)
    result = traced_search(query)

# EpisodeSession.__exit__ calls finish() automatically

# Batched mode (fewer HTTP calls — good for high-volume agents):
session = EpisodeSession(agent_id="my_agent", batch=True)
session.start()
traced = session.trace(my_tool)
traced(args)
session.finish()   # flushes all steps in one POST
```

For non-LangChain agents, simply omit `langsmith_run_id` (or pass `None`) — the
merger will score using step data only.

---

## Query API

After episodes are processed, query your data:

```bash
# List your episodes
GET /episodes?agent_id=my_agent_v1&limit=20

# Get full episode detail (steps + scores)
GET /episodes/ep_3f8a1c2d4e5b6f7a

# Get steps only (paginated)
GET /episodes/ep_3f8a1c2d4e5b6f7a/steps?limit=50&offset=0

# Poll merge job status
GET /jobs/ep_3f8a1c2d4e5b6f7a/status

# Find similar episodes (requires embeddings)
GET /similar?episode_id=ep_3f8a1c2d4e5b6f7a&k=5

# Search episode memory by task description
GET /recall?task=plan+a+trip+to+Paris&k=5
```

All requests require `Authorization: Bearer ageval-sk-<your-key>`.

---

## Run the merger worker (server-side)

```bash
# Required on the SERVER only:
AGEVAL_SUPABASE_URL=...
AGEVAL_SUPABASE_SERVICE_KEY=...
AGEVAL_ADMIN_SECRET=...      # required — no default, must be set explicitly

# Optional:
OPENAI_API_KEY=...           # for embeddings + LLM judge
LANGSMITH_API_KEY=...        # only needed for LangChain agents
AGEVAL_WEBHOOK_SECRET=...    # signs webhook payloads (HMAC-SHA256)

python -m merger.worker
```

---

## If tracing is not configured

If `AGEVAL_API_KEY` is not set, `trace_agent()` falls back to a plain
`agent.invoke()` — your agent runs normally with zero overhead.
No crashes, no exceptions.

---

## Run tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Security notes

- The `/register` endpoint is **disabled** unless `AGEVAL_ADMIN_SECRET` is set on the server.
  Never deploy without explicitly setting this to a strong random value.
- Webhook URLs are validated against SSRF blocklists at registration time.
- API keys are stored as SHA-256 hashes only — the raw key is never stored.