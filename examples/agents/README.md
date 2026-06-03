# AGeval Agent Fleet — realistic, many-tool agents across real frameworks

These examples exist to back a single claim: **AGeval evaluates real production
agents** — multi-tool agents, multi-agent crews, and agents whose tools are
served over MCP — not 2-tool toys.

Every agent here:

- makes **real LLM calls** (OpenAI or Anthropic) when you provide a key,
- uses a shared library of **21 production-shaped tools** (`toolkit.py`):
  SQL, HTTP, vector search, payments, orders, FX, calendar, email, Slack,
  ticketing, file I/O, sandboxed code execution, and a deliberately flaky
  upstream for error-handling coverage,
- routes through AGeval's tracers (`trace_openai`, `trace_anthropic`) or the
  framework-agnostic `AgentSession`, so each run becomes a **scored episode**.

The tools do real, deterministic local work — so the **only** cost of a run is
model tokens. That keeps a full sweep cheap and lets `BudgetGuard` bound spend
precisely.

## The fleet

| # | Agent | Framework | Tools exercised |
|---|-------|-----------|-----------------|
| 01 | Customer Support | OpenAI | customer, KB search, SQL, ticket, email |
| 02 | E-commerce Order | OpenAI | product, inventory, order, payment, email |
| 03 | Travel Concierge | OpenAI | weather, flights, FX, calendar |
| 04 | DevOps Incident | OpenAI | http_get (+env_error recovery), ticket, Slack |
| 05 | Financial Analyst | OpenAI | SQL, calculator, FX |
| 06 | RAG Research Assistant | Anthropic | vector search, http_get |
| 07 | Sales Outreach | Anthropic | SQL, customer, email, calendar |
| 08 | Coding Agent | Anthropic | write/read file, run_python |
| 09 | Support Router | **LangGraph** (StateGraph) | customer, KB, ticket, Slack |
| 10 | Data Pipeline | **LangGraph** (ReAct) | SQL, calculator, FX |
| 11 | Human-in-the-Loop Refund | **LangGraph** (interrupt/checkpoint) | customer, payment, email |
| 12 | Marketing Crew | **CrewAI** (2 agents) | KB search, Slack |
| 13 | Recruiting Crew | **CrewAI** (2 agents) | run_python, calendar, email |
| 14 | MCP Server + Client | **MCP** (real stdio/in-mem server) | customer, KB, ticket |
| 15 | MCP-backed Claude | **MCP** → Anthropic | customer, KB, ticket, Slack |
| 16 | Group Chat | **AutoGen** (2 agents) | SQL, calculator, customer |
| 17 | RPA Back-Office | framework-agnostic `AgentSession` | SQL, reconcile (flaky), ticket, file |

## Run it

```bash
# one agent
python examples/agents/01_customer_support_openai.py

# the whole fleet, with a single shared $0.50 Anthropic budget cap
python examples/agents/run_all.py

# only some, tighter cap, skip Claude
python examples/agents/run_all.py --only 01 05 14 --cap 0.25
python examples/agents/run_all.py --no-anthropic
```

### Keys

| Env var | Effect |
|---------|--------|
| `OPENAI_API_KEY` | runs the OpenAI / LangGraph / CrewAI / AutoGen / RPA agents live |
| `ANTHROPIC_API_KEY` | runs the Claude agents live (**capped by `BudgetGuard`**) |
| `AGEVAL_API_KEY` | records every episode to AGeval so it gets scored |

Without `AGEVAL_API_KEY` the agents still run live; they just aren't recorded.

### Optional frameworks

Agents 09–13 and 16 need their framework installed; each prints the exact
`pip install ...` line if it's missing. Nothing else in the repo depends on
them.

## Budget cap ($0.50)

When you plug in **your** Anthropic key, `run_all.py` wraps every `Anthropic()`
client in a single shared [`BudgetGuard`](budget_guard.py). Before each call it
projects the worst-case cost (real input-token count + full `max_tokens` of
output at that model's price) and **refuses any call that would cross the cap**,
then reconciles against the real `usage` afterwards. You cannot overspend; the
sweep just stops early and reports what was spent.

```python
from anthropic import Anthropic
from examples.agents.budget_guard import BudgetGuard
client = BudgetGuard(Anthropic(), usd_cap=0.50)   # pass straight into trace_anthropic
```
