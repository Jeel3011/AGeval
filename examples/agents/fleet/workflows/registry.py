"""
examples/agents/fleet/workflows/registry.py

A library of elaborate, real-life **multi-stage** agentic workflows (Phase 2A).
Each is a process a real company runs end-to-end — several live tool stages that
feed each other, ending in an LLM decision/synthesis over the accumulated
context. Every stage is a recorded AGeval step, so each run is a real ≥4-step
trajectory.

Contrast with `fleet/registry.py` (single-loop breadth agents): these are the
*depth* — branching pipelines, cross-tool data flow, optional side effects.

`ALL_WORKFLOWS` is the source of truth; `run_workflows.py` sweeps them.
"""

from __future__ import annotations

from examples.agents.fleet.workflows.base import Stage, WorkflowSpec

# Helper: build args from accumulating context. Stages run in order, so a later
# stage can read an earlier stage's output via context[<stage name>].


def _g(ctx, stage, *path, default=None):
    """Safely dig into a previous stage's (possibly nested) output."""
    cur = ctx.get(stage)
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return default
    return cur if cur is not None else default


_WORKFLOWS: list[WorkflowSpec] = [

    # ---- Insurance: property underwriting pipeline ----
    WorkflowSpec(
        id="wf.insurance.property_underwriting",
        vertical="insurance_risk",
        persona="a property-catastrophe underwriter",
        goal="Underwrite a commercial property at '350 Fifth Avenue, New York': locate it, "
             "assess seismic + air-quality + macro exposure, then decide accept/refer with a premium load.",
        stages=[
            Stage("geocode_site", "locate the insured property", tool="geocode",
                  args=lambda c: {"query": "350 Fifth Avenue, New York"}),
            Stage("seismic_risk", "check recent regional seismicity", tool="recent_earthquakes",
                  args=lambda c: {"min_magnitude": 4.5}),
            Stage("air_exposure", "pull local air quality at the site lat/lon", tool="air_quality",
                  args=lambda c: {"latitude": _g(c, "geocode_site", "lat", default=40.71),
                                  "longitude": _g(c, "geocode_site", "lon", default=-74.0)}),
            Stage("macro_context", "add macro context for the region", tool="world_bank_indicator",
                  args=lambda c: {"country": "US"}),
            Stage("decision", "decide accept/refer with a premium load and a one-line rationale",
                  llm_prompt=lambda c: f"Property: {c.get('geocode_site')}. Recent quakes: {c.get('seismic_risk')}. "
                                       f"Air quality: {c.get('air_exposure')}. Macro: {c.get('macro_context')}. "
                                       f"Give an accept/refer decision and a premium load %."),
        ],
    ),

    # ---- Finance: M&A diligence on two public companies ----
    WorkflowSpec(
        id="wf.finance.ma_diligence",
        vertical="finance_banking",
        persona="an M&A diligence analyst",
        goal="Run quick diligence comparing Apple (CIK 320193) and Microsoft (CIK 789019): pull both "
             "companies' 10-K facts, add macro context and recent scholarly signal, then write a one-page memo.",
        stages=[
            Stage("target_facts", "pull the target's 10-K facts", tool="sec_company_facts",
                  args=lambda c: {"cik": "320193"}),
            Stage("acquirer_facts", "pull the acquirer's 10-K facts", tool="sec_company_facts",
                  args=lambda c: {"cik": "789019"}),
            Stage("macro", "macro backdrop", tool="world_bank_indicator", args=lambda c: {"country": "US"}),
            Stage("research_signal", "scan recent scholarly works on the sector", tool="crossref_works",
                  args=lambda c: {"query": "consumer technology antitrust", "rows": 3}, optional=True),
            Stage("memo", "write the diligence memo with leverage ratios and a recommendation",
                  llm_prompt=lambda c: f"Target facts: {c.get('target_facts')}. Acquirer facts: {c.get('acquirer_facts')}. "
                                       f"Macro: {c.get('macro')}. Compute each leverage ratio (liabilities/assets) "
                                       f"and give a buy/hold recommendation."),
        ],
    ),

    # ---- Pharma: drug-safety triage with escalation ----
    WorkflowSpec(
        id="wf.pharma.drug_safety_triage",
        vertical="pharma_lifesci",
        persona="a pharmacovigilance officer",
        goal="Triage today's drug-safety picture: scan FDA recalls, map the diabetes trial landscape, "
             "pull supporting evidence, then summarise and (gated) post an alert to Slack.",
        stages=[
            Stage("recalls", "check ongoing FDA drug recalls", tool="openfda_enforcement",
                  args=lambda c: {"search": "status:Ongoing", "limit": 3}),
            Stage("trials", "map the trial landscape", tool="clinical_trials",
                  args=lambda c: {"condition": "diabetes", "limit": 3}),
            Stage("evidence", "pull supporting literature", tool="crossref_works",
                  args=lambda c: {"query": "drug recall pharmacovigilance", "rows": 3}, optional=True),
            Stage("brief", "summarise the safety signal and recommended action",
                  llm_prompt=lambda c: f"Recalls: {c.get('recalls')}. Trials: {c.get('trials')}. "
                                       f"Write a 3-line safety brief and state whether to escalate."),
            Stage("alert_slack", "post the brief to the safety channel (gated)", tool="post_slack",
                  args=lambda c: {"text": f"Drug-safety brief: {str(c.get('brief'))[:300]}",
                                  "channel": "#pharmacovigilance"}, optional=True),
        ],
    ),

    # ---- Logistics: supply-chain incident response ----
    WorkflowSpec(
        id="wf.logistics.incident_response",
        vertical="logistics_supplychain",
        persona="a supply-chain incident manager",
        goal="Respond to a potential disruption: check recent quakes + a key hub location + live last-mile "
             "capacity, devise a reroute, then (gated) POST the plan to the ops webhook.",
        stages=[
            Stage("disruption", "scan for disruptive seismic events", tool="recent_earthquakes",
                  args=lambda c: {"min_magnitude": 4.5}),
            Stage("hub", "locate the affected distribution hub", tool="geocode",
                  args=lambda c: {"query": "Port of Long Beach"}),
            Stage("last_mile", "check live last-mile capacity", tool="citybikes_network",
                  args=lambda c: {"network": "citi-bike-nyc"}),
            Stage("plan", "devise a 2-step reroute plan",
                  llm_prompt=lambda c: f"Quakes: {c.get('disruption')}. Hub: {c.get('hub')}. "
                                       f"Last-mile capacity: {c.get('last_mile')}. Give a 2-step reroute plan."),
            Stage("notify_ops", "POST the plan to the ops webhook (gated)", tool="post_webhook",
                  args=lambda c: {"target_url": "https://example.com/ops-webhook",
                                  "payload": {"plan": str(c.get("plan"))[:300]}}, optional=True),
        ],
    ),

    # ---- Legal/compliance: regulatory + sanctions monitor with audit row ----
    WorkflowSpec(
        id="wf.legal.compliance_monitor",
        vertical="legal_compliance",
        persona="a compliance monitoring analyst",
        goal="Run the daily compliance sweep: new AI rulemakings, an onboarding name screen against FBI "
             "wanted, a disclosure check on Tesla (CIK 1318605), then file an audit row.",
        stages=[
            Stage("rulemakings", "pull recent AI rulemakings", tool="federal_register",
                  args=lambda c: {"term": "artificial intelligence", "per_page": 3}),
            Stage("name_screen", "screen onboarding names against wanted listings", tool="fbi_wanted",
                  args=lambda c: {"page": 1}),
            Stage("disclosure", "check the issuer's latest 10-K", tool="sec_company_facts",
                  args=lambda c: {"cik": "1318605"}),
            Stage("summary", "summarise compliance posture and any flags",
                  llm_prompt=lambda c: f"Rulemakings: {c.get('rulemakings')}. Screen: {c.get('name_screen')}. "
                                       f"Disclosure: {c.get('disclosure')}. Summarise posture + any flags."),
            Stage("audit_row", "file an audit row (gated)", tool="db_write",
                  args=lambda c: {"table": "fleet_side_effects",
                                  "payload": {"kind": "compliance_audit", "summary": str(c.get("summary"))[:500]},
                                  "note": "compliance monitor audit"}, optional=True),
        ],
    ),

    # ---- Retail: new-supplier onboarding QA ----
    WorkflowSpec(
        id="wf.retail.supplier_onboarding_qa",
        vertical="retail_ecommerce",
        persona="a private-label QA specialist",
        goal="Onboard a new food supplier: verify a product's nutrition label, benchmark the live catalogue, "
             "convert a EUR cost, then decide approve/reject.",
        stages=[
            Stage("label", "verify the product's nutrition profile", tool="open_food_facts",
                  args=lambda c: {"barcode": "737628064502"}),
            Stage("catalog", "benchmark against the live catalogue", tool="fake_store_products",
                  args=lambda c: {"limit": 3}),
            Stage("cost_usd", "convert the EUR landed cost to USD", tool="frankfurter_fx",
                  args=lambda c: {"base": "EUR", "symbols": "USD"}),
            Stage("decision", "decide approve/reject with a margin note",
                  llm_prompt=lambda c: f"Label: {c.get('label')}. Catalogue: {c.get('catalog')}. "
                                       f"FX: {c.get('cost_usd')}. Approve or reject the supplier and why."),
        ],
    ),

    # ---- HR: market-aligned offer builder ----
    WorkflowSpec(
        id="wf.hr.offer_builder",
        vertical="hr_recruiting",
        persona="a compensation analyst",
        goal="Build a market-aligned offer for a remote data-science hire: pull market listings, convert a "
             "EUR base, add a relocation country brief, then propose a band.",
        stages=[
            Stage("market", "pull live market listings", tool="remote_jobs",
                  args=lambda c: {"industry": "data-science", "count": 3}),
            Stage("fx", "convert the EUR base to USD", tool="frankfurter_fx",
                  args=lambda c: {"base": "EUR", "symbols": "USD"}),
            Stage("relo", "pull a relocation country brief", tool="country_profile",
                  args=lambda c: {"country": "DE"}),
            Stage("proposal", "propose a compensation band with rationale",
                  llm_prompt=lambda c: f"Market: {c.get('market')}. FX: {c.get('fx')}. Relo: {c.get('relo')}. "
                                       f"Propose a USD comp band and a one-line rationale."),
        ],
    ),

    # ---- Energy: low-carbon dispatch planner ----
    WorkflowSpec(
        id="wf.energy.dispatch_planner",
        vertical="energy_utilities",
        persona="a grid dispatch planner",
        goal="Plan today's flexible-load dispatch: read grid carbon intensity + weather-driven demand + "
             "a relevant rulemaking, then recommend a dispatch window.",
        stages=[
            Stage("carbon", "read current grid carbon intensity", tool="carbon_intensity",
                  args=lambda c: {}),
            Stage("demand", "pull weather driving demand", tool="get_weather",
                  args=lambda c: {"latitude": 51.51, "longitude": -0.13}),
            Stage("policy", "check relevant clean-energy rulemakings", tool="federal_register",
                  args=lambda c: {"term": "clean energy", "per_page": 2}, optional=True),
            Stage("recommendation", "recommend a dispatch window",
                  llm_prompt=lambda c: f"Carbon: {c.get('carbon')}. Demand weather: {c.get('demand')}. "
                                       f"Recommend a low-carbon flexible-load dispatch window."),
        ],
    ),

    # ---- Real estate: acquisition screen ----
    WorkflowSpec(
        id="wf.realestate.acquisition_screen",
        vertical="realestate_proptech",
        persona="a CRE acquisitions analyst",
        goal="Screen an acquisition near '1600 Pennsylvania Avenue NW, Washington DC': locate it, check "
             "seismic + air livability + a public REIT comp, then score the deal.",
        stages=[
            Stage("locate", "geocode the asset", tool="geocode",
                  args=lambda c: {"query": "1600 Pennsylvania Avenue NW, Washington DC"}),
            Stage("seismic", "seismic exposure", tool="recent_earthquakes",
                  args=lambda c: {"min_magnitude": 4.5}),
            Stage("livability", "air livability at the asset", tool="air_quality",
                  args=lambda c: {"latitude": _g(c, "locate", "lat", default=38.9),
                                  "longitude": _g(c, "locate", "lon", default=-77.0)}),
            Stage("reit_comp", "pull a public REIT comp", tool="sec_company_facts",
                  args=lambda c: {"cik": "1045609"}),
            Stage("score", "score the deal 1-10 with a rationale",
                  llm_prompt=lambda c: f"Location: {c.get('locate')}. Seismic: {c.get('seismic')}. "
                                       f"Livability: {c.get('livability')}. REIT comp: {c.get('reit_comp')}. "
                                       f"Score the deal 1-10 and justify."),
        ],
    ),

    # ---- IT Ops: incident triage with notification ----
    WorkflowSpec(
        id="wf.itops.incident_triage",
        vertical="itops_devops_sre",
        persona="an SRE incident commander",
        goal="Triage a possible vendor outage: scan HN for outage chatter, locate the affected region, then "
             "summarise impact and (gated) POST a status update.",
        stages=[
            Stage("chatter", "scan HN for outage chatter", tool="hacker_news_top",
                  args=lambda c: {"limit": 5}),
            Stage("region", "locate the affected cloud region", tool="geocode",
                  args=lambda c: {"query": "Ashburn, Virginia"}),
            Stage("carbon_window", "check carbon for a safe maintenance window", tool="carbon_intensity",
                  args=lambda c: {}, optional=True),
            Stage("status", "summarise impact + recommended action",
                  llm_prompt=lambda c: f"Chatter: {c.get('chatter')}. Region: {c.get('region')}. "
                                       f"Summarise probable impact and the next action."),
            Stage("post_status", "POST the status update (gated)", tool="post_webhook",
                  args=lambda c: {"target_url": "https://example.com/status-webhook",
                                  "payload": {"status": str(c.get("status"))[:300]}}, optional=True),
        ],
    ),

    # ---- Government: grant oversight brief ----
    WorkflowSpec(
        id="wf.government.grant_oversight",
        vertical="government_public",
        persona="a public-spending oversight analyst",
        goal="Prepare an oversight brief: top federal spending agencies, recent environmental-justice "
             "rulemakings, and a regional hazard check, then write the brief.",
        stages=[
            Stage("spending", "pull top federal spending agencies", tool="usaspending_agency",
                  args=lambda c: {"fiscal_year": 2024}),
            Stage("rulemakings", "recent environmental-justice rulemakings", tool="federal_register",
                  args=lambda c: {"term": "environmental justice", "per_page": 3}),
            Stage("hazard", "regional hazard check", tool="recent_earthquakes",
                  args=lambda c: {"min_magnitude": 4.5}),
            Stage("brief", "write the oversight brief",
                  llm_prompt=lambda c: f"Spending: {c.get('spending')}. Rulemakings: {c.get('rulemakings')}. "
                                       f"Hazards: {c.get('hazard')}. Write a 4-sentence oversight brief."),
        ],
    ),

    # ---- Agriculture: spray-window + export decision ----
    WorkflowSpec(
        id="wf.agriculture.spray_and_export",
        vertical="agriculture_food",
        persona="an ag-operations agronomist",
        goal="Decide a spray window and an export call: read field weather + air quality + a pest taxonomy "
             "+ an export-market profile, then recommend.",
        stages=[
            Stage("weather", "field weather", tool="get_weather",
                  args=lambda c: {"latitude": 41.88, "longitude": -93.10}),
            Stage("air", "field air quality", tool="air_quality",
                  args=lambda c: {"latitude": 41.88, "longitude": -93.10}),
            Stage("pest", "confirm pest taxonomy", tool="gbif_species",
                  args=lambda c: {"name": "Spodoptera frugiperda"}),
            Stage("market", "export-market profile", tool="country_profile",
                  args=lambda c: {"country": "BR"}, optional=True),
            Stage("recommendation", "recommend a spray window and export call",
                  llm_prompt=lambda c: f"Weather: {c.get('weather')}. Air: {c.get('air')}. Pest: {c.get('pest')}. "
                                       f"Market: {c.get('market')}. Recommend a spray window and export call."),
        ],
    ),

    # ---- Scientific R&D: literature + space-ops dashboard ----
    WorkflowSpec(
        id="wf.science.research_dashboard",
        vertical="scientific_rnd",
        persona="a research program analyst",
        goal="Build a research dashboard: recent RLHF preprints, a citation pack, current ISS position and "
             "upcoming launches, then synthesise a weekly digest.",
        stages=[
            Stage("preprints", "recent preprints", tool="arxiv_search",
                  args=lambda c: {"query": "reinforcement learning from human feedback", "max_results": 3}),
            Stage("citations", "citation pack", tool="crossref_works",
                  args=lambda c: {"query": "graph neural networks", "rows": 3}),
            Stage("iss", "current ISS position", tool="iss_position", args=lambda c: {}),
            Stage("launches", "upcoming launches", tool="upcoming_launches",
                  args=lambda c: {"limit": 3}),
            Stage("digest", "synthesise the weekly digest",
                  llm_prompt=lambda c: f"Preprints: {c.get('preprints')}. Citations: {c.get('citations')}. "
                                       f"ISS: {c.get('iss')}. Launches: {c.get('launches')}. Write a weekly digest."),
        ],
    ),

    # ---- Sales: account-expansion brief ----
    WorkflowSpec(
        id="wf.sales.account_expansion",
        vertical="sales_crm",
        persona="an enterprise account executive",
        goal="Prep an expansion brief for a German account: market profile, FX for quota conversion, a "
             "competitive HN scan, then a 3-bullet plan.",
        stages=[
            Stage("market", "account market profile", tool="country_profile",
                  args=lambda c: {"country": "DE"}),
            Stage("fx", "FX for quota conversion", tool="frankfurter_fx",
                  args=lambda c: {"base": "EUR", "symbols": "USD"}),
            Stage("competitive", "competitive scan", tool="hacker_news_top",
                  args=lambda c: {"limit": 5}, optional=True),
            Stage("plan", "write a 3-bullet expansion plan",
                  llm_prompt=lambda c: f"Market: {c.get('market')}. FX: {c.get('fx')}. "
                                       f"Write a 3-bullet account-expansion plan."),
        ],
    ),

    # ---- Marketing: campaign launch kit (with real side effects) ----
    WorkflowSpec(
        id="wf.marketing.campaign_launch",
        vertical="marketing_content",
        persona="a campaign manager",
        goal="Assemble a launch kit: research the topic, screen the tagline for profanity, mint a trackable "
             "short link, and generate a booth QR.",
        stages=[
            Stage("research", "research the campaign topic", tool="wikipedia_summary",
                  args=lambda c: {"title": "Generative artificial intelligence"}),
            Stage("screen", "screen the tagline", tool="profanity_filter",
                  args=lambda c: {"text": "the smartest damn AI launch of the year"}),
            Stage("short_url", "mint a trackable short link", tool="short_link",
                  args=lambda c: {"url": "https://example.com/launch"}, optional=True),
            Stage("booth_qr", "generate a booth QR", tool="make_qr",
                  args=lambda c: {"text": "https://example.com/demo"}, optional=True),
            Stage("kit", "summarise the launch kit",
                  llm_prompt=lambda c: f"Research: {str(c.get('research'))[:300]}. Screen: {c.get('screen')}. "
                                       f"Short link: {c.get('short_url')}. QR: {c.get('booth_qr')}. "
                                       f"Summarise the ready launch kit."),
        ],
    ),

    # ---- Support: VIP escalation handler ----
    WorkflowSpec(
        id="wf.support.vip_escalation",
        vertical="support_success",
        persona="a senior support engineer",
        goal="Handle a VIP escalation: resolve the account region, define a disputed glossary term, scan for "
             "vendor outages, then draft a response.",
        stages=[
            Stage("region", "resolve the VIP account region", tool="zip_lookup",
                  args=lambda c: {"country": "us", "postal_code": "10001"}),
            Stage("term", "define the disputed term", tool="define_word",
                  args=lambda c: {"word": "indemnify"}),
            Stage("outages", "scan for vendor outages", tool="hacker_news_top",
                  args=lambda c: {"limit": 5}, optional=True),
            Stage("response", "draft the VIP response",
                  llm_prompt=lambda c: f"Region: {c.get('region')}. Term: {c.get('term')}. "
                                       f"Draft a concise, empathetic VIP response."),
        ],
    ),

    # ---- Healthcare: provider network add ----
    WorkflowSpec(
        id="wf.healthcare.network_add",
        vertical="healthcare_clinical",
        persona="a provider-network manager",
        goal="Add a provider to the network: verify the NPI, check trial activity for their specialty, scan "
             "active recalls, then approve/hold.",
        stages=[
            Stage("npi", "verify the provider NPI", tool="npi_lookup",
                  args=lambda c: {"npi": "1245319599"}),
            Stage("trials", "specialty trial activity", tool="clinical_trials",
                  args=lambda c: {"condition": "diabetes", "limit": 2}),
            Stage("recalls", "active recalls for safety context", tool="openfda_enforcement",
                  args=lambda c: {"search": "status:Ongoing", "limit": 2}, optional=True),
            Stage("decision", "approve or hold the provider",
                  llm_prompt=lambda c: f"NPI: {c.get('npi')}. Trials: {c.get('trials')}. "
                                       f"Approve or hold the provider and why."),
        ],
    ),

    # ---- Manufacturing: supplier-risk review ----
    WorkflowSpec(
        id="wf.manufacturing.supplier_risk",
        vertical="manufacturing_iot",
        persona="a supplier-risk engineer",
        goal="Review a key OEM supplier: pull Ford's 10-K (CIK 37996), check seismic risk to their region, "
             "convert a tooling quote, then score supplier risk.",
        stages=[
            Stage("financials", "pull the supplier's 10-K", tool="sec_company_facts",
                  args=lambda c: {"cik": "37996"}),
            Stage("seismic", "seismic risk to supplier regions", tool="recent_earthquakes",
                  args=lambda c: {"min_magnitude": 4.5}),
            Stage("quote_usd", "convert the tooling quote", tool="fx_rate",
                  args=lambda c: {"base": "JPY", "symbols": "USD"}),
            Stage("risk_score", "score supplier risk 1-5",
                  llm_prompt=lambda c: f"Financials: {c.get('financials')}. Seismic: {c.get('seismic')}. "
                                       f"FX: {c.get('quote_usd')}. Score supplier risk 1-5 and justify."),
        ],
    ),

    # ---- Travel: corporate destination readiness ----
    WorkflowSpec(
        id="wf.travel.destination_readiness",
        vertical="travel_hospitality",
        persona="a corporate-travel manager",
        goal="Assess destination readiness for Bangkok: city brief, local air quality, FX for per-diems, then "
             "a go/no-go note for sensitive travellers.",
        stages=[
            Stage("brief", "destination brief", tool="wikipedia_summary",
                  args=lambda c: {"title": "Bangkok"}),
            Stage("air", "local air quality", tool="air_quality",
                  args=lambda c: {"latitude": 13.76, "longitude": 100.50}),
            Stage("fx", "FX for per-diems", tool="frankfurter_fx",
                  args=lambda c: {"base": "USD", "symbols": "THB"}, optional=True),
            Stage("note", "write a go/no-go readiness note",
                  llm_prompt=lambda c: f"Brief: {str(c.get('brief'))[:300]}. Air: {c.get('air')}. FX: {c.get('fx')}. "
                                       f"Write a go/no-go note for sensitive travellers."),
        ],
    ),

    # ---- Education: course adoption kit ----
    WorkflowSpec(
        id="wf.education.course_adoption",
        vertical="education_edtech",
        persona="a curriculum designer",
        goal="Assemble a course-adoption kit for an algorithms course: source a textbook, build a vocab item, "
             "pull a faculty reading list, then a one-paragraph adoption rationale.",
        stages=[
            Stage("textbook", "source a textbook edition", tool="open_library",
                  args=lambda c: {"query": "introduction to algorithms"}),
            Stage("vocab", "build a vocab item", tool="define_word",
                  args=lambda c: {"word": "heuristic"}),
            Stage("reading", "faculty reading list", tool="crossref_works",
                  args=lambda c: {"query": "active learning pedagogy", "rows": 3}),
            Stage("rationale", "write an adoption rationale",
                  llm_prompt=lambda c: f"Textbook: {c.get('textbook')}. Vocab: {c.get('vocab')}. "
                                       f"Reading: {c.get('reading')}. Write an adoption rationale."),
        ],
    ),
]

ALL_WORKFLOWS: list[WorkflowSpec] = _WORKFLOWS


def verticals() -> list[str]:
    seen = []
    for w in ALL_WORKFLOWS:
        if w.vertical not in seen:
            seen.append(w.vertical)
    return seen


def by_vertical(v: str) -> list[WorkflowSpec]:
    return [w for w in ALL_WORKFLOWS if w.vertical == v]


def get(wf_id: str) -> WorkflowSpec:
    for w in ALL_WORKFLOWS:
        if w.id == wf_id:
            return w
    raise KeyError(f"no workflow {wf_id!r}")


if __name__ == "__main__":
    print(f"{len(ALL_WORKFLOWS)} workflows across {len(verticals())} verticals:")
    for w in ALL_WORKFLOWS:
        n_side = sum(1 for s in w.stages if s.tool in
                     __import__("examples.agents.sideeffects", fromlist=["TOOL_FUNCTIONS"]).TOOL_FUNCTIONS)
        print(f"  {w.id:42s} stages={len(w.stages)} side_effects={n_side} [{w.framework}]")
