# Elaborate Workflows + In-Eval Transparency (Phase 2)

Two things live here:

- **2A — elaborate, real-life multi-stage workflows.** Not single LLM loops:
  each workflow is a real business *process* — several live tool stages that
  feed each other, ending in an LLM decision/synthesis (and sometimes a real
  side-effect action). Every stage is a recorded AGeval step, so each run is a
  genuine ≥4-step trajectory the eval-memory trajectory/golden-path layers can
  score.
- **2B — transparency *during* evaluation.** Before each stage runs, the engine
  asks AGeval for a live `Verdict` (`session.evaluate_step`) and, with
  `--explain`, streams it — *watch the eval think*. After the run,
  `GET /episodes/{id}/explain` returns **score provenance**: which metrics
  dragged the score, the steps as evidence, and the live verdict trail.

20 workflows across all 20 verticals (M&A diligence, property underwriting,
drug-safety triage, supply-chain incident response, compliance monitor, grant
oversight, …). See [registry.py](registry.py).

## Run

```bash
# One workflow with the live transparency stream
python -m examples.agents.fleet.workflows.run_workflows --only wf.finance.ma_diligence --explain

# A whole vertical
python -m examples.agents.fleet.workflows.run_workflows --only finance_banking

# All workflows under a budget cap, with a complexity matrix
python -m examples.agents.fleet.workflows.run_workflows --cap 2.00

# A workflow that fires REAL side effects (short link, QR, Slack, webhook, db row)
python -m examples.agents.fleet.workflows.run_workflows \
    --only wf.marketing.campaign_launch --live-side-effects --explain
```

`--explain` output (one line per stage — the verdict is rendered *before* the
stage runs):

```
┌─ workflow wf.finance.ma_diligence  [pipeline]  finance_banking
│  ⟳ target_facts      verdict=allow    conf=0.00  allow (no concerns)
│  ✓ target_facts      {"entityName": "Apple Inc.", "Assets": {...}}
│  ⟳ acquirer_facts    verdict=allow    conf=0.00  allow (no concerns)
│  ✓ acquirer_facts    {"entityName": "MICROSOFT CORPORATION", ...}
│  ...
└─ episode ep_…  (5 steps)
```

Cold-start verdicts read `allow conf=0.00` honestly — the eval memory has no
baseline for a brand-new agent yet. After enough runs, the failure-signature,
baseline-z-score and golden-path layers light up and the verdicts gain teeth.

## Score provenance — `GET /episodes/{id}/explain`

After the merge/scoring worker has scored an episode:

```bash
curl -s "$AGEVAL_API_URL/episodes/<episode_id>/explain" \
     -H "Authorization: Bearer $AGEVAL_API_KEY" | jq
```

Returns a plain-English `summary`, a per-scorer `score_provenance` (metrics
ranked by `shortfall = 1 - value`, so the biggest score-draggers surface first),
`tools_used`, `failures` (with error classification), and the
`live_verdict_trail` rendered during the run. Everything is derived from already
recorded data — no re-scoring.

## How it relates to the rest

- Tools come from [real_tools.py](../../real_tools.py) (reads) and
  [sideeffects.py](../../sideeffects.py) (gated writes).
- Budget + the OpenAI cost cap are shared with the breadth fleet
  ([budget_openai.py](../budget_openai.py)).
- The live verdict reuses the shipped live-eval wedge (`POST /evaluate`,
  `session.evaluate_step`) — this is its user-facing read side.

## Tests

```bash
pytest tests/test_workflows.py                              # structural + provenance, offline
OPENAI_API_KEY=... AGEVAL_RUN_LIVE_AGENTS=1 \
    pytest tests/test_workflows.py -k live                  # opt-in live smoke
```
