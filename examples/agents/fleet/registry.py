"""
examples/agents/fleet/registry.py

The fleet: ~150 real business `AgentSpec`s across 20 industry verticals. Each
agent is a workload a real company runs — a credit analyst pulling 10-K facts,
a pharmacovigilance bot scanning FDA recalls, a logistics planner checking live
bike-share capacity, an IP paralegal searching patents. **None are toys** (no
"what's the weather" / "plan my trip" demos): every task is a concrete business
job whose answer depends on *live* external data.

Each spec names a subset of the real tools (real_tools.py for reads,
sideeffects.py for writes) and the framework that runs it. The factory turns a
spec into a real traced episode; the runner sweeps them under a budget cap.

`ALL_SPECS` is the single source of truth. `verticals()` and `by_vertical()`
help the runner build its coverage matrix.
"""

from __future__ import annotations

from examples.agents.fleet.factory import AgentSpec

# A compact persona shared shape — keeps system prompts consistent and terse so
# token cost per agent stays low (these run live).
_GUIDE = ("Use the tools to fetch live data — never invent numbers. Call a tool "
          "for every fact. Be concise: give the answer and the one or two figures "
          "that justify it.")


def _spec(id, vertical, persona, task, tools, *, framework="openai",
          side=None, system=None, max_iterations=6) -> AgentSpec:
    return AgentSpec(
        id=id, vertical=vertical, persona=persona,
        system_prompt=system or f"You are {persona}. {_GUIDE}",
        task=task, tools=tools, framework=framework,
        side_effect_tools=side or [], max_iterations=max_iterations)


# ---------------------------------------------------------------------------
# The 20 verticals. Each row: (id_suffix, persona, task, [tools], side=[...]).
# ~7-8 agents per vertical => ~150 total.
# ---------------------------------------------------------------------------
_VERTICALS: dict[str, list[tuple]] = {
    "support_success": [
        ("kb_answer", "a support agent", "A customer asks what 'serendipity' means in our docs glossary — define it precisely.", ["define_word"]),
        ("escalation_triage", "a support triage agent", "Summarise the top Hacker News stories so we can spot any thread mentioning an outage of a vendor we depend on.", ["hacker_news_top"]),
        ("status_lookup", "a customer-success agent", "Check the current UK grid carbon intensity — a customer's SLA credits depend on whether intensity is 'moderate' or worse right now.", ["carbon_intensity"]),
        ("doc_summary", "a knowledge-base curator", "Pull the Wikipedia summary of 'Service-level agreement' to seed a new help-center article.", ["wikipedia_summary"]),
        ("churn_signal", "a success analyst", "Look up related terms for 'cancel' to expand our churn-intent keyword list for ticket routing.", ["related_words"]),
        ("vip_region", "a support ops agent", "A VIP account is in postal code US 10001 — confirm the city/state so we route to the right regional CSM.", ["zip_lookup"]),
        ("incident_news", "a support comms agent", "Scan the latest spaceflight news for anything about a launch provider we resell, to pre-empt customer questions.", ["spaceflight_news"]),
        ("refund_fx", "a billing-support agent", "A customer was charged €59 but wants a USD refund — convert at the live rate so finance can process it.", ["frankfurter_fx"]),
    ],
    "sales_crm": [
        ("lead_enrich", "a sales-development rep", "Enrich an inbound lead named 'Alessandro' — estimate likely nationality so we route to the right regional team.", ["predict_nationality"]),
        ("account_sizing", "an account executive", "Size the German market for our expansion deck: pull Germany's population and income level.", ["country_profile"]),
        ("territory_fx", "a sales-ops analyst", "Our EU quotas are in EUR but reported in USD — pull the live EUR→USD rate to convert this quarter's pipeline.", ["frankfurter_fx"]),
        ("prospect_locate", "a field-sales rep", "A prospect HQ is at postal code DE 10115 — confirm the city so I can plan an on-site.", ["zip_lookup"]),
        ("icp_keywords", "a demand-gen marketer", "Expand our ICP keyword set: find words related to 'logistics' for ad targeting.", ["related_words"]),
        ("competitor_watch", "a competitive-intel analyst", "Check top Hacker News stories for any mention of a competitor launch we should brief sales on.", ["hacker_news_top"]),
        ("edu_segment", "a sales segmentation analyst", "List a few universities in the United States to seed an EDU-vertical outbound list.", ["universities"]),
        ("deal_currency", "a deal-desk analyst", "A deal is quoted in GBP; convert to our USD reporting currency at the live rate.", ["fx_rate"]),
    ],
    "marketing_content": [
        ("seo_expand", "an SEO strategist", "Build a semantic keyword cluster around 'ocean' for a sustainability campaign.", ["related_words"]),
        ("brand_safety", "a brand-safety reviewer", "Screen this user-submitted testimonial for profanity before we publish it: 'this damn product saved my week'.", ["profanity_filter"]),
        ("topic_research", "a content researcher", "Draft an intro paragraph from the Wikipedia summary of 'Generative artificial intelligence'.", ["wikipedia_summary"]),
        ("trend_scan", "a social-media manager", "Find the latest spaceflight news headlines for our aerospace client's newsletter.", ["spaceflight_news"]),
        ("glossary_build", "a content editor", "Define 'ephemeral' for our marketing glossary page.", ["define_word"]),
        ("launch_shortlink", "a campaign manager", "Create a trackable short link for our landing page https://example.com/launch and post the link.", ["wikipedia_summary"], ["short_link"]),
        ("qr_collateral", "a field-marketing lead", "Generate a QR code for our booth that encodes 'https://example.com/demo'.", ["wikipedia_summary"], ["make_qr"]),
    ],
    "finance_banking": [
        ("credit_10k", "a credit analyst", "Pull Apple's (CIK 320193) latest 10-K assets and liabilities from SEC EDGAR and flag the leverage ratio.", ["sec_company_facts"]),
        ("fx_hedge", "a treasury analyst", "We hold USD and owe EUR, GBP and JPY next week — pull live rates and report our exposure per currency.", ["fx_rate"]),
        ("macro_brief", "a macro strategist", "Pull US GDP (current US$) from the World Bank for this morning's rates note.", ["world_bank_indicator"]),
        ("crypto_desk", "a digital-assets trader", "Report BTC and ETH spot plus BTC's 24h move for the morning desk note.", ["crypto_price", "crypto_market"]),
        ("liquidity_check", "a corporate-banking analyst", "Pull Microsoft's (CIK 789019) latest 10-K assets vs liabilities and comment on liquidity.", ["sec_company_facts"]),
        ("sovereign_risk", "a sovereign-risk analyst", "Pull Brazil's GDP and income level for a country-risk memo.", ["world_bank_indicator", "country_profile"]),
        ("ecb_rates", "a fixed-income analyst", "Pull today's ECB reference rates (EUR base) for our euro-bond book.", ["frankfurter_fx"]),
    ],
    "insurance_risk": [
        ("cat_quake", "a catastrophe-risk modeler", "List significant earthquakes in the past day (mag >= 4.5) to flag exposed policies.", ["recent_earthquakes"]),
        ("recall_liability", "a product-liability underwriter", "Scan ongoing FDA drug recalls for any insured manufacturer's product.", ["openfda_enforcement"]),
        ("vehicle_uw", "an auto underwriter", "Decode VIN 1HGES16575L000000 to confirm make/model/year for a new auto policy.", ["decode_vin"]),
        ("climate_exposure", "a climate-risk analyst", "Check current UK grid carbon intensity to update our energy-sector transition-risk dashboard.", ["carbon_intensity"]),
        ("geo_underwrite", "a property underwriter", "Geocode '350 Fifth Avenue, New York' to plot the risk against our flood map.", ["geocode"]),
        ("country_risk", "a political-risk analyst", "Pull Nigeria's region, income level and population for a credit-insurance country file.", ["country_profile"]),
        ("air_health_claim", "a health-claims risk analyst", "Check current air quality at lat 34.05 lon -118.24 (LA) — high PM2.5 days correlate with respiratory claims.", ["air_quality"]),
    ],
    "healthcare_clinical": [
        ("provider_verify", "a provider-credentialing specialist", "Verify NPI 1245319599 in the NPPES registry before adding the provider to our network.", ["npi_lookup"]),
        ("trial_match", "a clinical research coordinator", "Find recent ClinicalTrials.gov studies for 'type 2 diabetes' to match eligible patients.", ["clinical_trials"]),
        ("drug_recall", "a pharmacy safety officer", "List ongoing FDA drug recalls so we can pull affected lots from the formulary.", ["openfda_enforcement"]),
        ("air_advisory", "a population-health analyst", "Check air quality at lat 40.71 lon -74.01 to decide whether to issue a respiratory advisory.", ["air_quality"]),
        ("evidence_review", "a medical librarian", "Find recent scholarly works on 'GLP-1 receptor agonists' via Crossref for a formulary review.", ["crossref_works"]),
        ("trial_oncology", "an oncology trials coordinator", "Find recent ClinicalTrials.gov studies for 'breast cancer' for our referral list.", ["clinical_trials"]),
        ("provider_org", "a network-management analyst", "Verify NPI 1083949324 in NPPES and report the organization name for a contract.", ["npi_lookup"]),
    ],
    "pharma_lifesci": [
        ("pv_signal", "a pharmacovigilance analyst", "Scan FDA enforcement reports for Class I drug recalls and summarise the safety signal.", ["openfda_enforcement"]),
        ("lit_review", "a medical-affairs scientist", "Pull recent arXiv preprints on 'protein structure prediction' for a competitive-science brief.", ["arxiv_search"]),
        ("trial_landscape", "a clinical-development strategist", "Map the ClinicalTrials.gov landscape for 'Alzheimer disease' to position our asset.", ["clinical_trials"]),
        ("crossref_cite", "a publications manager", "Find recent Crossref works on 'mRNA vaccine' to build a reference pack.", ["crossref_works"]),
        ("device_recall", "a device-quality engineer", "Check FDA enforcement for ongoing recalls (search status:Ongoing) relevant to our device line.", ["openfda_enforcement"]),
        ("species_tox", "a tox-screening scientist", "Confirm the GBIF taxonomy for 'Danio rerio' (zebrafish) used in our assay.", ["gbif_species"]),
        ("kol_arxiv", "a scientific-comms lead", "Pull recent arXiv preprints on 'single cell RNA sequencing' for a KOL engagement brief.", ["arxiv_search"]),
    ],
    "retail_ecommerce": [
        ("catalog_audit", "a merchandising analyst", "Pull a sample of the live product catalogue and flag any item priced over $100.", ["fake_store_products"]),
        ("nutri_compliance", "a private-label QA specialist", "Look up barcode 737628064502 in Open Food Facts and report its Nutri-Score for our label-claims review.", ["open_food_facts"]),
        ("price_fx", "a pricing analyst", "Our supplier invoices in EUR — convert a €49.99 cost to USD at the live rate for margin analysis.", ["frankfurter_fx"]),
        ("review_moderation", "a marketplace trust-and-safety agent", "Moderate this review for profanity before display: 'what the hell, fast shipping'.", ["profanity_filter"]),
        ("assortment_local", "a local-assortment planner", "List breweries in 'portland' to plan a local craft-beer endcap.", ["breweries"]),
        ("book_sourcing", "a media-category buyer", "Search Open Library for 'clean code' to source titles for our tech-books category.", ["open_library"]),
        ("promo_qr", "a retail-ops coordinator", "Generate a QR code linking to 'https://example.com/sale' for in-store signage.", ["fake_store_products"], ["make_qr"]),
    ],
    "logistics_supplychain": [
        ("last_mile_bikes", "a last-mile operations planner", "Check live citi-bike-nyc station capacity and flag the busiest stations for courier rebalancing.", ["citybikes_network"]),
        ("port_geocode", "a freight-routing analyst", "Geocode 'Port of Rotterdam' to plot it on our routing map.", ["geocode"]),
        ("fleet_vin", "a fleet-maintenance manager", "Decode VIN 1FTFW1ET5DFC10312 to confirm the truck's make/model/year for the service record.", ["decode_vin"]),
        ("customs_fx", "an import/export analyst", "Convert a £12,000 customs valuation to USD at the live rate for the entry filing.", ["fx_rate"]),
        ("quake_disruption", "a supply-chain risk planner", "List significant earthquakes in the past day to flag at-risk supplier regions.", ["recent_earthquakes"]),
        ("hub_population", "a network-design analyst", "Pull Germany's population to weight a candidate distribution hub.", ["country_profile"]),
        ("carbon_routing", "a sustainability logistics lead", "Check UK grid carbon intensity now to decide whether to schedule EV-fleet charging.", ["carbon_intensity"]),
    ],
    "manufacturing_iot": [
        ("supplier_quake", "a plant-continuity engineer", "List recent significant earthquakes to assess risk to our overseas component suppliers.", ["recent_earthquakes"]),
        ("part_vin", "an aftermarket-parts engineer", "Decode VIN JH4KA8260MC000000 to confirm the vehicle platform for a part fitment check.", ["decode_vin"]),
        ("energy_schedule", "an industrial-energy manager", "Check UK carbon intensity to schedule a high-load production run at a low-carbon window.", ["carbon_intensity"]),
        ("air_safety", "an EHS compliance officer", "Check outdoor air quality at lat 41.88 lon -87.63 (Chicago plant) for today's worker-exposure log.", ["air_quality"]),
        ("rd_research", "an R&D materials engineer", "Find recent arXiv papers on 'solid state battery' for a materials scouting memo.", ["arxiv_search"]),
        ("commodity_fx", "a procurement analyst", "Convert a ¥1,500,000 tooling quote to USD at the live rate for the capex request.", ["fx_rate"]),
        ("oem_10k", "a supplier-finance analyst", "Pull Ford's (CIK 37996) latest 10-K assets and liabilities to assess a key OEM customer's health.", ["sec_company_facts"]),
    ],
    "energy_utilities": [
        ("grid_carbon", "a grid-operations analyst", "Report the current UK grid carbon intensity and whether it's 'low', 'moderate' or 'high' for dispatch decisions.", ["carbon_intensity"]),
        ("demand_weather", "a load-forecasting analyst", "Pull current weather at lat 51.51 lon -0.13 (London) to adjust today's electricity demand forecast.", ["get_weather"]),
        ("commodity_oil", "an energy-trading analyst", "Pull live FX (USD base) for EUR and GBP to price a cross-border power trade.", ["fx_rate"]),
        ("seismic_assets", "a pipeline-integrity engineer", "List recent earthquakes (mag >= 4.5) to check for seismic risk near our pipeline corridors.", ["recent_earthquakes"]),
        ("emissions_air", "an environmental-compliance analyst", "Check air quality at lat 29.76 lon -95.37 (Houston) for our emissions-monitoring log.", ["air_quality"]),
        ("policy_watch", "a regulatory-affairs analyst", "Search the US Federal Register for recent documents on 'clean energy' for a policy brief.", ["federal_register"]),
        ("utility_10k", "a utility-credit analyst", "Pull NextEra Energy's (CIK 753308) latest 10-K assets vs liabilities for a credit review.", ["sec_company_facts"]),
    ],
    "realestate_proptech": [
        ("comp_geocode", "a real-estate appraiser", "Geocode '1600 Pennsylvania Avenue NW, Washington DC' to anchor a comps search.", ["geocode"]),
        ("market_sizing", "a CRE market analyst", "Pull France's population and income level to size a retail-leasing opportunity.", ["country_profile"]),
        ("flood_quake", "a property-risk analyst", "List recent significant earthquakes to flag seismic risk for a West-Coast portfolio.", ["recent_earthquakes"]),
        ("zip_demo", "a residential analyst", "Confirm the city/state for US postal code 94110 for a neighborhood report.", ["zip_lookup"]),
        ("rent_fx", "an international-investments analyst", "Convert a €2,200/mo Berlin rent to USD at the live rate for an investor memo.", ["frankfurter_fx"]),
        ("air_livability", "a residential-listings analyst", "Check air quality at lat 37.77 lon -122.42 (San Francisco) for a listing's livability score.", ["air_quality"]),
        ("reit_10k", "a REIT-investment analyst", "Pull Prologis's (CIK 1045609) latest 10-K assets and liabilities for an acquisition screen.", ["sec_company_facts"]),
    ],
    "travel_hospitality": [
        ("destination_brief", "a destination-content editor", "Write a two-line city brief for guests from the Wikipedia summary of 'Kyoto'.", ["wikipedia_summary"]),
        ("fx_desk", "a hotel revenue manager", "Convert tonight's €189 ADR to USD at the live rate for the central revenue report.", ["frankfurter_fx"]),
        ("local_geocode", "a concierge-systems engineer", "Geocode 'Colosseum, Rome' to add it to our points-of-interest database.", ["geocode"]),
        ("event_news", "an events coordinator", "Scan top Hacker News stories for any tech-conference news relevant to our corporate-bookings team.", ["hacker_news_top"]),
        ("guest_air", "a guest-experience manager", "Check air quality at lat 13.76 lon 100.50 (Bangkok) to advise sensitive guests.", ["air_quality"]),
        ("loyalty_qr", "a loyalty-program manager", "Generate a QR code for the loyalty sign-up page 'https://example.com/join'.", ["wikipedia_summary"], ["make_qr"]),
        ("destination_news", "a travel-content strategist", "Pull top Hacker News stories for any remote-work or travel-tech trend for our digital-nomad blog.", ["hacker_news_top"]),
    ],
    "legal_compliance": [
        ("reg_watch", "a regulatory-compliance counsel", "Search the US Federal Register for recent 'artificial intelligence' rulemakings for a compliance alert.", ["federal_register"]),
        ("sanctions_news", "a financial-crime analyst", "Pull the current FBI Wanted listings to cross-check against an onboarding name screen.", ["fbi_wanted"]),
        ("disclosure_10k", "a securities-compliance analyst", "Pull Tesla's (CIK 1318605) latest 10-K revenue figure from SEC EDGAR for a disclosure check.", ["sec_company_facts"]),
        ("contract_term", "a contracts paralegal", "Define the term 'indemnify' precisely for a contract glossary.", ["define_word"]),
        ("spend_transparency", "a public-procurement analyst", "Pull the top US federal spending agencies for FY2024 from USAspending for a transparency report.", ["usaspending_agency"]),
        ("ip_research", "an IP research analyst", "Find recent Crossref works on 'patent litigation' for a prior-art reading list.", ["crossref_works"]),
        ("aml_screen", "a KYC/AML analyst", "Cross-check the name 'Said' against current FBI Wanted listings for an onboarding screen.", ["fbi_wanted"]),
    ],
    "hr_recruiting": [
        ("market_jobs", "a talent-market analyst", "Pull current remote data-science job listings to benchmark our role against the market.", ["remote_jobs"]),
        ("name_diversity", "a DEI analytics specialist", "Estimate the likely nationality distribution for the first name 'Wei' for an aggregate diversity model.", ["predict_nationality"]),
        ("campus_list", "a campus-recruiting coordinator", "List a few universities in the United States to seed this season's campus target list.", ["universities"]),
        ("comp_fx", "a global-compensation analyst", "Convert a €75,000 Berlin offer to USD at the live rate for the comp committee.", ["frankfurter_fx"]),
        ("age_estimate", "a workforce-planning analyst", "Estimate the typical age for the first name 'Margaret' for a retirement-risk cohort model.", ["predict_age"]),
        ("eng_jobs", "a recruiting-ops analyst", "Pull current remote engineering job listings to size the competitive talent pool.", ["remote_jobs"]),
        ("relo_country", "a global-mobility specialist", "Pull Canada's capital, region and income level for a relocation-package brief.", ["country_profile"]),
    ],
    "itops_devops_sre": [
        ("incident_news", "an SRE on-call", "Scan top Hacker News stories for any reported outage of a cloud provider we depend on.", ["hacker_news_top"]),
        ("status_geo", "a network-operations engineer", "Geocode 'Ashburn, Virginia' to map a data-center region on our topology view.", ["geocode"]),
        ("cve_research", "a security engineer", "Find recent arXiv papers on 'prompt injection' to brief our AppSec team.", ["arxiv_search"]),
        ("capacity_carbon", "a platform-sustainability engineer", "Check UK carbon intensity now to decide whether to run a batch job in a low-carbon window.", ["carbon_intensity"]),
        ("webhook_alert", "an observability engineer", "Post a test alert payload to our incident webhook to verify the integration end-to-end.", ["hacker_news_top"], ["post_webhook"]),
        ("dns_region", "a cloud-ops analyst", "Confirm the city/state for US postal code 98109 (a candidate edge POP).", ["zip_lookup"]),
        ("vendor_news", "a SaaS-vendor-management analyst", "Scan top Hacker News stories for any acquisition or shutdown news about a SaaS vendor we depend on.", ["hacker_news_top"]),
    ],
    "government_public": [
        ("spend_audit", "a public-spending auditor", "Pull the top US federal spending agencies for FY2024 from USAspending for an oversight memo.", ["usaspending_agency"]),
        ("reg_digest", "a policy analyst", "Summarise recent US Federal Register documents on 'environmental justice' for a legislative digest.", ["federal_register"]),
        ("wanted_check", "a public-safety analyst", "Pull current FBI Wanted listing titles for a regional bulletin.", ["fbi_wanted"]),
        ("census_brief", "a demographics analyst", "Pull the United States' population and income level for a public dashboard.", ["country_profile"]),
        ("disaster_quake", "an emergency-management coordinator", "List significant earthquakes in the past day to update the regional hazard board.", ["recent_earthquakes"]),
        ("procure_currency", "a federal-procurement analyst", "Convert a €30,000 vendor quote to USD at the live rate for a solicitation.", ["fx_rate"]),
        ("seismic_alert", "a public-works engineer", "List recent significant earthquakes and confirm a candidate site by geocoding 'Sacramento, California'.", ["recent_earthquakes", "geocode"]),
    ],
    "education_edtech": [
        ("uni_directory", "an admissions-data analyst", "List universities in 'Canada' to expand our partner-institution directory.", ["universities"]),
        ("vocab_builder", "a curriculum designer", "Build a vocabulary exercise: give the definition and related words for 'photosynthesis'.", ["define_word", "related_words"]),
        ("research_reading", "an academic-librarian", "Find recent Crossref works on 'active learning pedagogy' for a faculty reading list.", ["crossref_works"]),
        ("topic_explainer", "an instructional-content writer", "Draft a student-friendly intro from the Wikipedia summary of 'Photosynthesis'.", ["wikipedia_summary"]),
        ("stem_news", "a STEM outreach coordinator", "Pull the latest spaceflight news for a classroom current-events module.", ["spaceflight_news"]),
        ("moderation", "an edtech trust-and-safety agent", "Screen this student forum post for profanity: 'this assignment is a damn nightmare'.", ["profanity_filter"]),
        ("library_sourcing", "a course-materials librarian", "Search Open Library for 'introduction to algorithms' to source a textbook edition.", ["open_library"]),
    ],
    "agriculture_food": [
        ("crop_weather", "an ag-operations agronomist", "Pull current weather at lat 41.88 lon -93.10 (Iowa farmland) for today's spray-window decision.", ["get_weather"]),
        ("food_label", "a food-safety QA specialist", "Look up barcode 5000159484695 in Open Food Facts and report brand and Nutri-Score for a supplier audit.", ["open_food_facts"]),
        ("commodity_fx", "a commodity-trading analyst", "Convert a €210/tonne wheat price to USD at the live rate for a hedging note.", ["frankfurter_fx"]),
        ("pest_species", "an entomology research tech", "Confirm the GBIF taxonomy for 'Spodoptera frugiperda' (fall armyworm) for a pest report.", ["gbif_species"]),
        ("recall_food", "a food-recall coordinator", "Scan FDA enforcement reports for ongoing food-related recalls affecting our SKUs.", ["openfda_enforcement"]),
        ("air_field", "a field-safety supervisor", "Check air quality at lat 36.75 lon -119.77 (Fresno) before scheduling outdoor crew work.", ["air_quality"]),
        ("export_country", "an ag-export analyst", "Pull Brazil's population, region and income level to assess it as a soy-export market.", ["country_profile"]),
    ],
    "scientific_rnd": [
        ("preprint_scout", "a research scientist", "Pull recent arXiv preprints on 'reinforcement learning from human feedback' for a lab journal club.", ["arxiv_search"]),
        ("citation_pack", "a research librarian", "Find recent Crossref works on 'graph neural networks' to assemble a citation pack.", ["crossref_works"]),
        ("seismology", "a geophysics researcher", "List significant earthquakes in the past day for a near-real-time seismicity log.", ["recent_earthquakes"]),
        ("biodiversity", "a biodiversity researcher", "Confirm the GBIF taxonomy and rank for 'Apis mellifera' (honey bee).", ["gbif_species"]),
        ("space_ops", "an aerospace research analyst", "Report the current ISS position and the next upcoming rocket launches for a tracking dashboard.", ["iss_position", "upcoming_launches"]),
        ("econ_indicator", "a computational social scientist", "Pull Japan's GDP (current US$) from the World Bank for an econometric model.", ["world_bank_indicator"]),
        ("lexicography", "a computational-linguistics researcher", "Pull the definition and related words for 'entropy' to seed a domain lexicon.", ["define_word", "related_words"]),
    ],
}


def _build_all() -> list[AgentSpec]:
    specs: list[AgentSpec] = []
    for vertical, rows in _VERTICALS.items():
        for row in rows:
            suffix, persona, task, tools = row[0], row[1], row[2], row[3]
            side = row[4] if len(row) > 4 else []
            specs.append(_spec(f"{vertical}.{suffix}", vertical, persona, task, tools, side=side))
    return specs


ALL_SPECS: list[AgentSpec] = _build_all()


def verticals() -> list[str]:
    return list(_VERTICALS.keys())


def by_vertical(vertical: str) -> list[AgentSpec]:
    return [s for s in ALL_SPECS if s.vertical == vertical]


def get(spec_id: str) -> AgentSpec:
    for s in ALL_SPECS:
        if s.id == spec_id:
            return s
    raise KeyError(f"no spec with id {spec_id!r}")


if __name__ == "__main__":
    from collections import Counter
    counts = Counter(s.vertical for s in ALL_SPECS)
    print(f"{len(ALL_SPECS)} specs across {len(_VERTICALS)} verticals:")
    for v in _VERTICALS:
        print(f"  {v:24s} {counts[v]}")
