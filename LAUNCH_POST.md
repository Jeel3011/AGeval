# Show HN: AGeval – Agents regress. Here's how to catch it before your users do.

Hi HN,

I'm excited to share **AGeval**, a framework-agnostic behavioral memory layer for production LLM agents.

When building agents, everyone focuses on getting the first 100 runs to work. You use LangGraph or CrewAI, write a few prompts, and it looks like magic. But what happens in week 4 when you tweak a system prompt to fix an edge case, and suddenly your agent starts infinitely looping on a simple search task?

**Agents don't just break; they drift.** A prompt tweak that improves task A often subtly degrades task B. Traditional observability tools (like LangSmith or DataDog) are great at showing you *what* your agent did, but they are terrible at telling you if your agent is getting *better or worse* over time.

We built AGeval to solve this.

### How it works
AGeval sits quietly alongside your agent code (with a 2-line SDK wrap). Instead of just dumping raw traces, it does three things:

1. **Task Clustering (The "Memory" Layer)**: It embeds the incoming tasks and uses K-Means to group your agent's runs into "recurring task types" (e.g., "SQL Data Retrieval" vs. "Email Drafting").
2. **Behavioral Scoring**: It uses rule-based heuristics (like tool repetition/reasoning coverage) and an optional LLM-as-a-judge to score the trajectory of every single episode out of 100%.
3. **Drift Detection**: It compares the average score of each task cluster week-over-week. 

### Gating PRs with Behavioral Drift
The coolest part: We provide a GitHub Action (`ageval-action`). You can drop it into your CI pipeline. If your new prompt tweak causes a `▼ -10%` drift in your "Data Retrieval" cluster, **the PR fails**. It will even tell you the top failing tool in that cluster so you know exactly where to debug.

### Open Source & Framework Agnostic
The evaluation engine, scoring, and metrics registry are all open-source. It doesn't matter if you use LangChain, OpenAI's native tool calling, Anthropic, or pure Python—AGeval just expects you to trace the tool boundary.

**Links:**
* GitHub: [https://github.com/Jeel3011/AGeval](https://github.com/Jeel3011/AGeval)
* Demo Dashboard: [demo.ageval.dev](https://demo.ageval.dev)
* PyPI: `pip install ageval`

I'd love for you to try it out. If you've struggled with your agents regressing after "fixing" a bug, I'd love to hear how you're currently handling it! I'll be hanging out in the comments all day to answer questions.
