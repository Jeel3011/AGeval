# ageval

Episodic evaluation framework for LangGraph agents.
Traces every tool call, scores agent behavior, stores embeddings.
Zero changes to your agent code.

---

## Install

```bash
# from PyPI (once published)
pip install ageval

# or directly from GitHub
pip install git+https://github.com/YOUR_USERNAME/agent-eval.git#subdirectory=ageval_package
```

---

## Setup — 3 steps, nothing else

**Step 1 — Add env vars to your `.env`**

```bash
AGEVAL_SUPABASE_URL=https://jmvmzfgzihkmpwnytmxt.supabase.co
AGEVAL_SUPABASE_SERVICE_KEY=your_service_role_key
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=ageval-demo
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

**Step 3 — Run the merger worker** (in `agent-eval` repo)

```bash
python -m merger.worker
```

That's it. Every agent run is now:
- Traced (every tool call captured with input, output, latency, error category)
- Scored (success rate, recovery rate, reasoning coverage, efficiency)
- Embedded (pgvector for similarity search)
- Stored in Supabase

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

## If tracing is not configured

If `AGEVAL_SUPABASE_URL` is not set, `trace_agent()` falls back to a plain
`agent.invoke()` — your agent runs normally with zero overhead.
No crashes, no exceptions.

---

## Supported frameworks

- LangGraph (any graph compiled with `.compile()`)
- LangChain agents (any chain with `.invoke()`)
- Any agent that accepts a LangChain `callbacks` config parameter