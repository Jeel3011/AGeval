# The Real-Agent Fleet

**142 real business agents across 20 industry verticals**, each running a real
OpenAI brain against **live external APIs** (and, opt-in, **real side effects**),
recorded as scored AGeval episodes.

This is the answer to "AGeval evaluates real production agents, not toys." The
older `examples/agents/NN_*.py` fleet makes real LLM calls but against a
deterministic *local* toolkit. This fleet calls **live public/government/
finance/science APIs** — data changes run-to-run, hosts rate-limit and 5xx for
real, and that liveness is used as a "this is not a toy" assertion.

| | Old fleet (`toolkit.py`) | This fleet (`real_tools.py`) |
|---|---|---|
| LLM | real OpenAI/Anthropic | real OpenAI |
| Tools | fake in-memory dicts | **real live HTTP APIs** |
| Errors | simulated `raise` | **real** timeouts / 429 / 404 from live hosts |
| Side effects | none | **real** Supabase / is.gd / QR / webhook (+ gated email/Slack) |
| Determinism | fully deterministic | **live** — used as a realness check |

## Layout

- [`real_tools.py`](../real_tools.py) — ~40 real read tools (weather, geo, FX,
  crypto, SEC EDGAR, openFDA, ClinicalTrials, USGS, arXiv, Crossref, NHTSA,
  CityBikes, Open Food Facts, …) behind a **polite HTTP client** (declared
  User-Agent, per-host rate limiting, backoff on 429/5xx, no caching).
- [`sideeffects.py`](../sideeffects.py) — real side-effecting tools with an
  honest credential gate (see below).
- [`registry.py`](registry.py) — the 142 `AgentSpec` rows.
- [`factory.py`](factory.py) — turns a spec into a real traced episode.
- [`run_fleet.py`](run_fleet.py) — sweeps the fleet under a budget cap and prints
  a vertical × framework coverage matrix.
- [`flagships/`](flagships/) — hand-written framework-depth agents on real
  LangGraph (StateGraph + ReAct), MCP, and zero-code `import ageval.auto`.
- [`budget_openai.py`](budget_openai.py) — hard USD spend cap (OpenAI analogue of
  the Anthropic `budget_guard.py`).

## Run it

```bash
# Whole fleet, $3 hard cap, read-only
python -m examples.agents.fleet.run_fleet

# One vertical, tighter cap
python -m examples.agents.fleet.run_fleet --only finance_banking --cap 0.50

# ~1 agent per vertical (cheap smoke of all 20)
python -m examples.agents.fleet.run_fleet --sample 1

# A single agent by id
python -m examples.agents.fleet.run_fleet --only finance_banking.credit_10k

# Enable REAL side effects (writes a Supabase row, mints a real is.gd link, …)
python -m examples.agents.fleet.run_fleet --only itops_devops_sre --live-side-effects

# Framework flagships (LangGraph / MCP / zero-code auto)
python -m examples.agents.fleet.flagships.run_flagships

# Prove the tools are live (re-run: prices / ISS / quakes change)
python -m examples.agents.real_tools
```

Recording requires a reachable AGeval API (`AGEVAL_API_URL` + `AGEVAL_API_KEY`).
With no key the agents still run live (real LLM + real APIs) but aren't recorded.

## The 20 verticals

Support & Success · Sales & CRM · Marketing & Content · Finance & Banking ·
Insurance & Risk · Healthcare & Clinical Ops · Pharma & Life Sciences ·
Retail & E-commerce · Logistics & Supply Chain · Manufacturing & Industrial IoT ·
Energy & Utilities · Real Estate & PropTech · Travel & Hospitality ·
Legal & Compliance · HR & Recruiting · IT Ops / DevOps / SRE ·
Government & Public Sector · Education & EdTech · Agriculture & Food ·
Scientific Research & R&D.

Every agent is a concrete business job (a credit analyst pulling 10-K facts, a
pharmacovigilance bot scanning FDA recalls, a last-mile planner checking live
bike-share capacity). No "what's the weather" / "plan my trip" demos.

## Side effects: credential → capability (honest gate)

All side effects are master-gated behind `AGEVAL_LIVE_SIDE_EFFECTS=1`, so a
read-only sweep never mutates anything. Within that, each tool is real now or
activates the moment a key is dropped in `.env` (otherwise it reports
`needs <KEY>` — never a fake send):

| Tool | Real today? | Needs |
|---|---|---|
| `db_write` (Supabase insert) | ✅ | `AGEVAL_SUPABASE_SERVICE_KEY` (+ URL) |
| `short_link` (is.gd) | ✅ | nothing |
| `make_qr` (goQR) | ✅ | nothing |
| `post_webhook` | ✅ | a target URL (passed as an argument) |
| `send_email` (Resend) | gated | `RESEND_API_KEY` |
| `post_slack` (Incoming Webhook) | gated | `SLACK_WEBHOOK_URL` |

Check what's live right now:

```bash
python -m examples.agents.sideeffects
```

## Tests

```bash
pytest tests/test_real_fleet.py                              # structural, offline
OPENAI_API_KEY=... AGEVAL_RUN_LIVE_AGENTS=1 \
    pytest tests/test_real_fleet.py -k live                  # opt-in live smoke
```

## Honest limits

- `send_email` / `post_slack` / Calendar / Drive **sends** need provider creds
  not in `.env` by default; until added they report `needs <KEY>` (no faking).
- Public APIs rate-limit and occasionally 5xx — that's *desirable* (real
  `env_error` coverage); the polite client backs off and the sweep continues.
- A full live sweep costs real OpenAI tokens — bounded by the budget guard,
  which stops early and reports spend rather than overspending.
