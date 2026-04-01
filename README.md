# ageval

Episodic evaluation framework for LangGraph agents.
Traces every tool call, scores agent behaviour, stores embeddings.
**Zero changes to your agent code.**

---

## Install

```bash
# from PyPI (once published)
pip install ageval

# or directly from GitHub
pip install git+https://github.com/Jeel3011/AGeval.git#subdirectory=ageval_package
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
| `tool_input` | What was passed in |
| `tool_output` | What came back |
| `success` | Did it work |
| `error_category` | `agent_error` / `env_error` / `unknown` |
| `is_recoverable` | Should the agent retry |
| `reasoning` | Why the agent made this call (from LLM output) |
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
Uses GPT-4o-mini to evaluate:

| Metric | What it measures |
|---|---|
| `task_completion` | Did the agent achieve the stated goal? |
| `reasoning_quality` | Was the chain-of-thought coherent? |
| `error_handling` | Did the agent recover gracefully from failures? |
| `output_quality` | Is the final output useful and accurate? |

Both scorers write to `episode_scores` with their respective `scorer` name.

### Custom weights

```python
from eval.rules import score_episode

result = score_episode(client, episode_id, weights={
    "success_rate"      : 0.4,
    "recovery_rate"     : 0.3,
    "reasoning_coverage": 0.15,
    "efficiency_score"  : 0.15,
})
```

---

## Query API

After episodes are processed, query your data:

```bash
# List your episodes
GET /episodes?agent_id=my_agent_v1&limit=20

# Get full episode detail (steps + scores)
GET /episodes/ep_3f8a1c2d4e5b6f7a

# Get steps only
GET /episodes/ep_3f8a1c2d4e5b6f7a/steps

# Find similar episodes (requires embeddings)
GET /similar?episode_id=ep_3f8a1c2d4e5b6f7a&k=5
```

All requests require `Authorization: Bearer ageval-sk-<your-key>`.

---

## Run the merger worker (server-side)

```bash
# Env vars needed on the SERVER (not the user's machine):
AGEVAL_SUPABASE_URL=...
AGEVAL_SUPABASE_SERVICE_KEY=...
LANGSMITH_API_KEY=...
OPENAI_API_KEY=...   # optional — for embeddings + LLM judge

python -m merger.worker
```

---

## If tracing is not configured

If `AGEVAL_API_KEY` is not set, `trace_agent()` falls back to a plain
`agent.invoke()` — your agent runs normally with zero overhead.
No crashes, no exceptions.

---

## Lower-level SDK (for fine-grained control)

```python
from sdk import EpisodeSession

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

---

## Run tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Supported frameworks

- LangGraph (any graph compiled with `.compile()`)
- LangChain agents (any chain with `.invoke()`)
- Any agent that accepts a LangChain `callbacks` config parameter
- Manual integration via `@episodic_trace` decorator or `EpisodeSession`