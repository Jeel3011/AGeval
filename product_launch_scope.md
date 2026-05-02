# AGeval — Product Launch Scope Discussion

## What We've Proven Works (Today)

| Component | Status | Evidence |
|-----------|--------|----------|
| SDK (`trace_agent`) | ✅ Working | Real LangGraph trip planner: 3 tool calls captured automatically |
| API Server | ✅ Working | 27 E2E tests + 114 unit tests + real agent test all pass |
| Eval Engine (rules) | ✅ Working | 4 metrics scored in real-time (success rate, recovery, reasoning, efficiency) |
| Schema / RLS | ✅ Working | Multi-tenant isolation verified, idempotent schema |
| Security | ✅ Hardened | SSRF protection, input validation, key rotation, rate limiting |
| CI/CD | ✅ Passing | Lint + tests + type checking |

---

## How Users Would Integrate (3 Lines of Code)

```python
from ageval import trace_agent

# Wrap your existing agent — nothing else changes
result = trace_agent(
    agent    = your_langgraph_agent,
    input    = {"messages": [("user", "your prompt")]},
    agent_id = "your-agent-v1",
    task     = "description of what the agent should do",
)
```

For the trip planner specifically:
```python
from ageval import trace_agent
result = trace_agent(agent=trip_planner_graph, input=user_input, agent_id="trip_planner_v2")
```

That's it. Every tool call, error, latency, and reasoning trace is captured automatically.

---

## Product Scope: What to Launch With vs What to Add Later

### 🚀 MVP (Launch Now) — What We Have

> [!IMPORTANT]
> The core value proposition is already built: **zero-config agent evaluation with automatic tracing**.

1. **SDK** — `pip install ageval` + `trace_agent()` wrapper
2. **Scoring** — 4-metric composite score (success rate, recovery rate, reasoning coverage, efficiency)
3. **API** — RESTful ingestion + query endpoints with API key auth
4. **Dashboard** — Basic episode viewer (already exists in `/dashboard`)
5. **Webhooks** — Alert on low scores with HMAC verification
6. **Similarity Search** — pgvector-powered "find episodes like this one"

### 🔧 Phase 2 (First Month Post-Launch)

7. **LLM Judge** — Already partially built (`eval/llm_judge.py`), needs polish
8. **Trend Dashboard** — Score over time charts, regression alerts
9. **Multi-framework Support** — CrewAI, AutoGen, raw OpenAI function calling
10. **PyPI Publishing** — `pip install ageval` from public PyPI

### 🏗️ Phase 3 (Growth)

11. **Hosted Mode** — SaaS version (no self-hosting needed)
12. **Team Features** — Multiple API keys per org, shared dashboards
13. **CI Integration** — GitHub Action that runs agent tests and blocks merge on score regression
14. **Benchmark Suites** — Pre-built evaluation tasks per domain (travel, coding, research)

---

## Key Questions to Decide Before Launch

### 1. Target Audience

> **Who's the first user?**

| Option | Pros | Cons |
|--------|------|------|
| **Open-source devs** building LangGraph agents | Large TAM, viral, community | Support burden, hard to monetize |
| **Teams/startups** shipping agents to production | Paying customers, clear pain | Smaller reach, need enterprise features |
| **Your own agents** (trip planner, etc.) | Dogfooding, fast iteration | Not a business yet |

### 2. Deployment Model

| Option | Effort | Monetization |
|--------|--------|-------------|
| **Self-hosted only** (current) | ✅ Ready now | Open-source/freemium |
| **Hosted SaaS** (you run the infra) | 2-4 weeks work | Subscription ($29-99/mo) |
| **Both** | Best long-term | Free tier + paid tiers |

### 3. Competitive Positioning

Current landscape:
- **LangSmith** — Full tracing platform (Heavyweight, $$$)
- **Braintrust** — Eval + logging (broad, not agent-specific)
- **AgentOps** — Agent observability (similar space)

**AGeval's angle**: *"Zero-config evaluation for LangGraph agents. Add one line of code, get a reliability score."*

What makes AGeval different:
- **Episodic** — treats each agent run as a unit, not individual LLM calls
- **Automatic** — no manual labeling or eval dataset needed
- **Score-first** — immediately gives you a number (not just traces)
- **Lightweight** — self-host with Supabase, no vendor lock-in

### 4. What's Missing for a Public Launch?

> [!WARNING]
> Critical gaps before putting this in front of external users:

| Gap | Effort | Priority |
|-----|--------|----------|
| **README / docs** — No user-facing documentation | 1-2 days | 🔴 Critical |
| **PyPI package** — Can't `pip install ageval` yet | 1 hour | 🔴 Critical |
| **Onboarding flow** — New users can't self-serve (need to manually create API keys) | 1 day | 🟡 High |
| **Error messages** — Some errors return raw stack traces | Half day | 🟡 High |
| **Secret rotation** — Current credentials are exposed in git history | 30 min manual | 🔴 Critical |
| **Rate limit tuning** — 100 req/min may be too low for batch ingestion | Config change | 🟢 Low |

### 5. Integration with Your Trip Planner

This is the perfect dogfooding story. Here's the plan:

```
trip-planner repo                    agent-eval repo
─────────────────                    ───────────────
pip install ageval                   API running on Railway
                                          ↓
from ageval import trace_agent       ← receives steps
result = trace_agent(                ← scores episode
    agent=trip_graph,                ← stores history
    input=user_query,
    agent_id="trip_planner_v2",      dashboard shows results →
)
```

---

## Recommended Launch Path

> [!TIP]
> **Recommended: Launch as open-source tool for LangGraph developers, dogfood with your trip planner.**

### Week 1: Polish
- [ ] Write README with quickstart (install → trace → score in 5 minutes)
- [ ] Publish to PyPI as `ageval`
- [ ] Rotate all compromised credentials
- [ ] Integrate into your trip planner repo
- [ ] Deploy API to Railway/Fly.io

### Week 2: Soft Launch
- [ ] Post on r/LangChain, LangGraph Discord
- [ ] Collect feedback from 5-10 users
- [ ] Fix top 3 pain points

### Week 3-4: Iterate
- [ ] Add LLM Judge scoring
- [ ] Polish dashboard with score trends
- [ ] Build GitHub Action for CI scoring

---

## Bottom Line

**The core product works.** We just proved it with a real LangGraph agent. 

The question isn't "does it work?" — it's "who do you want using it first, and how do you want to distribute it?" That decision drives everything else.
