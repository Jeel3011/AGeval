// Real data mirrored from examples/agents/fleet/registry.py and
// examples/agents/fleet/workflows/registry.py — used by the landing showcases.
// Kept in sync by hand; counts match the live fleet (142 agents, 20 verticals,
// 20 workflows).

export const FLEET_VERTICALS: { label: string; count: number }[] = [
  { label: "Support & Success", count: 8 },
  { label: "Sales & CRM", count: 8 },
  { label: "Marketing & Content", count: 7 },
  { label: "Finance & Banking", count: 7 },
  { label: "Insurance & Risk", count: 7 },
  { label: "Healthcare & Clinical", count: 7 },
  { label: "Pharma & Life Sciences", count: 7 },
  { label: "Retail & E-commerce", count: 7 },
  { label: "Logistics & Supply Chain", count: 7 },
  { label: "Manufacturing & IoT", count: 7 },
  { label: "Energy & Utilities", count: 7 },
  { label: "Real Estate & PropTech", count: 7 },
  { label: "Travel & Hospitality", count: 7 },
  { label: "Legal & Compliance", count: 7 },
  { label: "HR & Recruiting", count: 7 },
  { label: "IT Ops / SRE", count: 7 },
  { label: "Government & Public", count: 7 },
  { label: "Education & EdTech", count: 7 },
  { label: "Agriculture & Food", count: 7 },
  { label: "Scientific R&D", count: 7 },
];

export const FLEET_TOTAL = FLEET_VERTICALS.reduce((a, v) => a + v.count, 0);

export type WorkflowStage = string; // tool name or "synth"
export const WORKFLOWS: { title: string; vertical: string; stages: WorkflowStage[] }[] = [
  { title: "property underwriting", vertical: "Insurance", stages: ["geocode", "recent_earthquakes", "air_quality", "world_bank", "synth"] },
  { title: "M&A diligence", vertical: "Finance", stages: ["sec_facts", "sec_facts", "world_bank", "crossref", "synth"] },
  { title: "drug-safety triage", vertical: "Pharma", stages: ["openfda", "clinical_trials", "crossref", "synth", "post_slack"] },
  { title: "incident response", vertical: "Logistics", stages: ["earthquakes", "geocode", "citybikes", "synth", "post_webhook"] },
  { title: "compliance monitor", vertical: "Legal", stages: ["fed_register", "fbi_wanted", "sec_facts", "synth", "db_write"] },
  { title: "supplier onboarding QA", vertical: "Retail", stages: ["open_food_facts", "fakestore", "fx", "synth"] },
  { title: "offer builder", vertical: "HR", stages: ["remote_jobs", "fx", "country", "synth"] },
  { title: "dispatch planner", vertical: "Energy", stages: ["carbon", "weather", "fed_register", "synth"] },
  { title: "acquisition screen", vertical: "Real Estate", stages: ["geocode", "earthquakes", "air_quality", "sec_facts", "synth"] },
  { title: "incident triage", vertical: "IT Ops", stages: ["hacker_news", "geocode", "carbon", "synth", "post_webhook"] },
  { title: "grant oversight", vertical: "Government", stages: ["usaspending", "fed_register", "earthquakes", "synth"] },
  { title: "spray & export", vertical: "Agriculture", stages: ["weather", "air_quality", "gbif", "country", "synth"] },
  { title: "research dashboard", vertical: "Science R&D", stages: ["arxiv", "crossref", "iss", "launches", "synth"] },
  { title: "account expansion", vertical: "Sales", stages: ["country", "fx", "hacker_news", "synth"] },
  { title: "campaign launch", vertical: "Marketing", stages: ["wikipedia", "profanity", "short_link", "make_qr", "synth"] },
  { title: "VIP escalation", vertical: "Support", stages: ["zip_lookup", "define", "hacker_news", "synth"] },
  { title: "network add", vertical: "Healthcare", stages: ["npi_lookup", "clinical_trials", "openfda", "synth"] },
  { title: "supplier risk", vertical: "Manufacturing", stages: ["sec_facts", "earthquakes", "fx", "synth"] },
  { title: "destination readiness", vertical: "Travel", stages: ["wikipedia", "air_quality", "fx", "synth"] },
  { title: "course adoption", vertical: "Education", stages: ["open_library", "define", "crossref", "synth"] },
];
