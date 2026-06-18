"""
examples/agents/real_tools.py

A library of **real** tools for the AGeval fleet. Unlike `toolkit.py` (which
does deterministic *local* work so example runs are free), every tool here
performs a **real HTTP call to a live, public API**. The data changes run to
run — that liveness is used as a "this is not a toy" assertion by the fleet
runner.

It mirrors `toolkit.py`'s public surface exactly so existing agents, tracers
and the MCP examples can swap it in unchanged:

    TOOL_FUNCTIONS            # {name: callable}
    openai_schemas(names)     # OpenAI function-calling schemas
    anthropic_schemas(names)  # Anthropic tool-use schemas
    subset(names)             # {name: callable} restricted to names
    mcp_manifest(names)       # MCP tools/list manifest

Error contract (matches AGeval's classifier exactly, like toolkit.py):
  - network/timeout/5xx/429  -> ConnectionError / TimeoutError  -> env_error
  - bad input / 4xx / parse  -> ValueError                      -> agent_error

The shared `polite_get` / `polite_post` client handles the realities of live
public APIs: a declared User-Agent (SEC EDGAR, Nominatim and weather.gov
require one), per-host rate limiting, a timeout, and exponential backoff on
429/5xx. There is deliberately **no response caching** — data must be live.

Run a quick realness check:

    python -m examples.agents.real_tools

Each tool is called once and its live output printed; re-run and values such
as crypto prices, the ISS position, or the latest quakes will have changed.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

import requests

# A declared, honest User-Agent. Several APIs (SEC EDGAR, OSM Nominatim,
# api.weather.gov) reject requests without one. Overridable via env.
USER_AGENT = os.environ.get(
    "AGEVAL_HTTP_USER_AGENT",
    "AGeval-Fleet/1.0 (+https://github.com/ageval; real-agent-evaluation)",
)
DEFAULT_TIMEOUT = float(os.environ.get("AGEVAL_HTTP_TIMEOUT", "20"))
MAX_RETRIES = int(os.environ.get("AGEVAL_HTTP_RETRIES", "3"))

# ---------------------------------------------------------------------------
# Polite HTTP client: per-host rate limiting + backoff + honest UA, no cache.
# ---------------------------------------------------------------------------
# Minimum seconds between requests to the same host. Conservative so we stay
# good citizens of free public APIs (Nominatim asks for <=1 req/s).
_MIN_INTERVAL = float(os.environ.get("AGEVAL_HTTP_MIN_INTERVAL", "1.1"))
_host_lock = threading.Lock()
_last_call: dict[str, float] = {}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _host_of(url: str) -> str:
    # cheap host extraction without urllib import noise
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].lower()


def _throttle(host: str) -> None:
    """Block until at least _MIN_INTERVAL has passed since the last call to
    this host. Per-host so unrelated APIs don't serialise on each other."""
    with _host_lock:
        now = time.monotonic()
        last = _last_call.get(host, 0.0)
        wait = _MIN_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def _request(method: str, url: str, *, headers: dict | None = None,
             timeout: float | None = None, **kw) -> requests.Response:
    """One real HTTP call with throttle + retry/backoff. Maps failures onto the
    AGeval error contract:
        - transport errors / timeouts / 5xx / 429 -> ConnectionError (env_error)
        - 4xx (except 429)                         -> ValueError      (agent_error)
    """
    host = _host_of(url)
    hdrs = dict(_session.headers)
    if headers:
        hdrs.update(headers)
    timeout = timeout or DEFAULT_TIMEOUT
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES):
        _throttle(host)
        try:
            resp = _session.request(method, url, headers=hdrs, timeout=timeout, **kw)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            time.sleep(min(2 ** attempt, 8))
            continue

        # Retry on 429 / 5xx with exponential backoff.
        if resp.status_code == 429 or resp.status_code >= 500:
            last_exc = ConnectionError(
                f"{host} returned {resp.status_code} (attempt {attempt + 1}/{MAX_RETRIES})")
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(2 ** attempt, 8)
            except ValueError:
                delay = min(2 ** attempt, 8)
            time.sleep(delay)
            continue

        # 4xx other than 429 is the caller's fault — agent_error, no retry.
        if 400 <= resp.status_code < 500:
            raise ValueError(f"{host} returned {resp.status_code}: {resp.text[:200]}")

        return resp

    # Exhausted retries on a transient/env failure.
    raise ConnectionError(f"failed to reach {host} after {MAX_RETRIES} attempts: {last_exc}")


def polite_get(url: str, *, params: dict | None = None, headers: dict | None = None,
               timeout: float | None = None) -> requests.Response:
    return _request("GET", url, params=params, headers=headers, timeout=timeout)


def polite_post(url: str, *, json: Any = None, data: Any = None,
                headers: dict | None = None, timeout: float | None = None) -> requests.Response:
    return _request("POST", url, json=json, data=data, headers=headers, timeout=timeout)


def _json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise ValueError(f"non-JSON response from {resp.url}: {exc}") from exc


# ===========================================================================
# Real read tools (batch 1). Each does a live HTTP call.
# ===========================================================================

# --- Weather / climate ----------------------------------------------------
def get_weather(latitude: float, longitude: float) -> dict:
    """Current weather at a lat/lon via Open-Meteo (no auth)."""
    r = polite_get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": latitude, "longitude": longitude, "current_weather": True})
    cw = _json(r).get("current_weather")
    if not cw:
        raise ValueError("no current_weather in Open-Meteo response")
    return cw


def air_quality(latitude: float, longitude: float) -> dict:
    """Current PM2.5 / PM10 / ozone at a lat/lon via Open-Meteo air-quality."""
    r = polite_get("https://air-quality-api.open-meteo.com/v1/air-quality", params={
        "latitude": latitude, "longitude": longitude,
        "current": "pm10,pm2_5,ozone,european_aqi"})
    return _json(r).get("current", {})


def carbon_intensity() -> dict:
    """Current UK grid carbon intensity (gCO2/kWh) — UK Carbon Intensity API."""
    r = polite_get("https://api.carbonintensity.org.uk/intensity")
    data = _json(r).get("data") or []
    if not data:
        raise ValueError("no carbon-intensity data returned")
    return data[0]


# --- Geo / location --------------------------------------------------------
def geocode(query: str) -> dict:
    """Resolve a place name to lat/lon + display name via OSM Nominatim."""
    r = polite_get("https://nominatim.openstreetmap.org/search", params={
        "q": query, "format": "json", "limit": 1})
    hits = _json(r)
    if not hits:
        raise ValueError(f"no geocoding result for {query!r}")
    top = hits[0]
    return {"lat": float(top["lat"]), "lon": float(top["lon"]),
            "display_name": top.get("display_name")}


def zip_lookup(country: str, postal_code: str) -> dict:
    """Look up places for a postal code via Zippopotam.us (no auth)."""
    r = polite_get(f"https://api.zippopotam.us/{country}/{postal_code}")
    return _json(r)


# --- Finance / FX ----------------------------------------------------------
def fx_rate(base: str = "USD", symbols: str = "EUR,GBP,JPY") -> dict:
    """Live exchange rates for `base` via open.er-api.com (no auth)."""
    r = polite_get(f"https://open.er-api.com/v6/latest/{base.upper()}")
    payload = _json(r)
    rates = payload.get("rates") or {}
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return {"base": payload.get("base_code", base.upper()),
            "rates": {s: rates[s] for s in wanted if s in rates},
            "as_of": payload.get("time_last_update_utc")}


def world_bank_indicator(country: str = "US", indicator: str = "NY.GDP.MKTP.CD") -> dict:
    """Latest value of a World Bank indicator (default: GDP, current US$)."""
    r = polite_get(
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
        params={"format": "json", "per_page": "1", "mrnev": "1"})
    payload = _json(r)
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise ValueError("no World Bank data for that country/indicator")
    row = payload[1][0]
    return {"country": row["country"]["value"], "indicator": row["indicator"]["value"],
            "date": row["date"], "value": row["value"]}


# --- Crypto ----------------------------------------------------------------
def crypto_price(ids: str = "bitcoin,ethereum", vs: str = "usd") -> dict:
    """Live spot prices from CoinGecko (no auth)."""
    r = polite_get("https://api.coingecko.com/api/v3/simple/price", params={
        "ids": ids, "vs_currencies": vs})
    return _json(r)


# --- Government / regulatory ----------------------------------------------
def sec_company_facts(cik: str) -> dict:
    """Latest reported facts for a company from SEC EDGAR (10-digit CIK).
    Requires a declared User-Agent (handled by the polite client)."""
    cik10 = str(cik).strip().lstrip("CIK").zfill(10)
    # SEC EDGAR's fair-access policy demands a UA naming a real contact; their
    # CDN 403s a generic one. Use AGEVAL_SEC_CONTACT (an email) when provided.
    contact = os.environ.get("AGEVAL_SEC_CONTACT", "ageval-fleet@example.com")
    r = polite_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
                   headers={"User-Agent": f"AGeval-Fleet {contact}"})
    payload = _json(r)
    facts = payload.get("facts", {}).get("us-gaap", {})
    out: dict[str, Any] = {"entityName": payload.get("entityName"), "cik": cik10}
    # Pull the most recent annual figure for a couple of headline concepts.
    for concept in ("Assets", "Liabilities", "Revenues"):
        units = facts.get(concept, {}).get("units", {}).get("USD", [])
        annual = [u for u in units if u.get("form") == "10-K"]
        if annual:
            latest = max(annual, key=lambda u: u.get("end", ""))
            out[concept] = {"value": latest.get("val"), "end": latest.get("end")}
    return out


def federal_register(term: str = "artificial intelligence", per_page: int = 3) -> dict:
    """Recent US Federal Register documents matching a term (no auth)."""
    r = polite_get("https://www.federalregister.gov/api/v1/documents.json", params={
        "conditions[term]": term, "per_page": per_page,
        "order": "newest", "fields[]": "title"})
    payload = _json(r)
    return {"count": payload.get("count"),
            "titles": [d.get("title") for d in payload.get("results", [])]}


# --- Science / space -------------------------------------------------------
def iss_position() -> dict:
    """Current latitude/longitude of the ISS via Open-Notify (no auth).
    Changes every call — a clean liveness signal."""
    r = polite_get("http://api.open-notify.org/iss-now.json")
    payload = _json(r)
    pos = payload.get("iss_position", {})
    return {"latitude": float(pos["latitude"]), "longitude": float(pos["longitude"]),
            "timestamp": payload.get("timestamp")}


def recent_earthquakes(min_magnitude: float = 4.5) -> dict:
    """Significant earthquakes in the past day from USGS (no auth)."""
    r = polite_get(
        "https://earthquake.usgs.gov/fdsnws/event/1/query",
        params={"format": "geojson", "starttime": "now-1days",
                "minmagnitude": min_magnitude, "orderby": "time", "limit": 5})
    feats = _json(r).get("features", [])
    return {"count": len(feats),
            "events": [{"place": f["properties"].get("place"),
                        "mag": f["properties"].get("mag")} for f in feats]}


def arxiv_search(query: str = "large language models", max_results: int = 3) -> dict:
    """Recent arXiv papers matching a query (Atom feed, no auth)."""
    r = polite_get("http://export.arxiv.org/api/query", params={
        "search_query": f"all:{query}", "max_results": max_results,
        "sortBy": "submittedDate", "sortOrder": "descending"})
    # arXiv returns Atom XML; pull titles without an XML dep.
    titles = []
    for chunk in r.text.split("<entry>")[1:]:
        if "<title>" in chunk:
            titles.append(chunk.split("<title>")[1].split("</title>")[0].strip())
    if not titles:
        raise ValueError("no arXiv entries parsed")
    return {"query": query, "titles": titles}


# --- More finance / markets ------------------------------------------------
def crypto_market(coin: str = "btc-bitcoin") -> dict:
    """24h market stats for a coin from Coinpaprika (no auth). Ids look like
    'btc-bitcoin', 'eth-ethereum'."""
    r = polite_get(f"https://api.coinpaprika.com/v1/tickers/{coin}")
    d = _json(r)
    usd = d.get("quotes", {}).get("USD", {})
    return {"symbol": d.get("symbol"), "priceUsd": usd.get("price"),
            "changePercent24Hr": usd.get("percent_change_24h"),
            "marketCapUsd": usd.get("market_cap")}


def frankfurter_fx(base: str = "EUR", symbols: str = "USD,GBP") -> dict:
    """ECB reference FX rates via Frankfurter (no auth)."""
    r = polite_get("https://api.frankfurter.app/latest", params={"from": base, "to": symbols})
    return _json(r)


# --- Government / regulatory (more) ---------------------------------------
def usaspending_agency(fiscal_year: int = 2024) -> dict:
    """Top US federal spending agencies for a fiscal year (USAspending)."""
    r = polite_post("https://api.usaspending.gov/api/v2/spending/", json={
        "type": "agency", "filters": {"fy": str(fiscal_year), "quarter": "4"}})
    results = _json(r).get("results", [])[:5]
    return {"fiscal_year": fiscal_year,
            "top": [{"name": x.get("name"), "amount": x.get("amount")} for x in results]}


def fbi_wanted(page: int = 1) -> dict:
    """Current FBI Wanted listings (no auth)."""
    r = polite_get("https://api.fbi.gov/wanted/v1/list", params={"page": page})
    items = _json(r).get("items", [])[:5]
    return {"titles": [i.get("title") for i in items]}


def country_profile(country: str = "DE") -> dict:
    """Region / capital / income level + latest population for a country via the
    World Bank (no auth, very reliable host). `country` is an ISO2/ISO3 code."""
    meta = polite_get(f"https://api.worldbank.org/v2/country/{country}",
                      params={"format": "json"})
    payload = _json(meta)
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise ValueError(f"no World Bank country profile for {country!r}")
    c = payload[1][0]
    out = {"name": c.get("name"), "region": c.get("region", {}).get("value"),
           "capital": c.get("capitalCity"), "income_level": c.get("incomeLevel", {}).get("value")}
    pop = polite_get(
        f"https://api.worldbank.org/v2/country/{country}/indicator/SP.POP.TOTL",
        params={"format": "json", "per_page": "1", "mrnev": "1"})
    rows = _json(pop)
    if isinstance(rows, list) and len(rows) > 1 and rows[1]:
        out["population"] = rows[1][0].get("value")
    return out


# --- Health / medical ------------------------------------------------------
def openfda_enforcement(search: str = "status:Ongoing", limit: int = 3) -> dict:
    """Recent FDA drug enforcement (recall) reports (openFDA, no auth)."""
    r = polite_get("https://api.fda.gov/drug/enforcement.json", params={
        "search": search, "limit": limit})
    results = _json(r).get("results", [])
    return {"recalls": [{"reason": x.get("reason_for_recall", "")[:120],
                         "firm": x.get("recalling_firm"),
                         "classification": x.get("classification")} for x in results]}


def npi_lookup(npi: str = "1245319599") -> dict:
    """Look up a US healthcare provider in the NPPES NPI registry (no auth)."""
    r = polite_get("https://npiregistry.cms.hhs.gov/api/", params={
        "number": npi, "version": "2.1"})
    results = _json(r).get("results", [])
    if not results:
        raise ValueError(f"no NPI record for {npi!r}")
    basic = results[0].get("basic", {})
    return {"name": basic.get("organization_name") or
            f"{basic.get('first_name','')} {basic.get('last_name','')}".strip(),
            "enumeration_type": results[0].get("enumeration_type")}


def clinical_trials(condition: str = "diabetes", limit: int = 3) -> dict:
    """Recent ClinicalTrials.gov studies for a condition (v2 API, no auth)."""
    r = polite_get("https://clinicaltrials.gov/api/v2/studies", params={
        "query.cond": condition, "pageSize": limit})
    studies = _json(r).get("studies", [])
    titles = [s.get("protocolSection", {}).get("identificationModule", {}).get("briefTitle")
              for s in studies]
    return {"condition": condition, "titles": titles}


# --- Science / space (more) -----------------------------------------------
def crossref_works(query: str = "machine learning", rows: int = 3) -> dict:
    """Scholarly works matching a query via Crossref (no auth)."""
    r = polite_get("https://api.crossref.org/works", params={"query": query, "rows": rows})
    items = _json(r).get("message", {}).get("items", [])
    return {"titles": [(i.get("title") or [""])[0] for i in items]}


def upcoming_launches(limit: int = 3) -> dict:
    """Upcoming orbital rocket launches via The Space Devs Launch Library 2
    (no auth)."""
    r = polite_get("https://ll.thespacedevs.com/2.2.0/launch/upcoming/", params={
        "limit": limit, "mode": "list"})
    results = _json(r).get("results", [])
    return {"launches": [{"name": x.get("name"), "net": x.get("net"),
                          "provider": (x.get("launch_service_provider") or {}).get("name")}
                         for x in results]}


def spaceflight_news(limit: int = 3) -> dict:
    """Latest spaceflight news headlines (Spaceflight News API, no auth)."""
    r = polite_get("https://api.spaceflightnewsapi.net/v4/articles", params={"limit": limit})
    return {"titles": [a.get("title") for a in _json(r).get("results", [])]}


def gbif_species(name: str = "Panthera leo") -> dict:
    """Match a species name in the GBIF taxonomic backbone (no auth)."""
    r = polite_get("https://api.gbif.org/v1/species/match", params={"name": name})
    d = _json(r)
    return {"scientificName": d.get("scientificName"), "rank": d.get("rank"),
            "kingdom": d.get("kingdom"), "matchType": d.get("matchType")}


# --- Transit / logistics / vehicles ---------------------------------------
def decode_vin(vin: str = "1HGES16575L000000") -> dict:
    """Decode a vehicle VIN via NHTSA vPIC (no auth)."""
    r = polite_get(
        f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}",
        params={"format": "json"})
    results = _json(r).get("Results", [])
    if not results:
        raise ValueError(f"no VIN decode for {vin!r}")
    d = results[0]
    return {"make": d.get("Make"), "model": d.get("Model"),
            "year": d.get("ModelYear"), "type": d.get("VehicleType")}


def citybikes_network(network: str = "citi-bike-nyc") -> dict:
    """Live station availability for a bike-share network (CityBikes, no auth)."""
    r = polite_get(f"https://api.citybik.es/v2/networks/{network}")
    stations = _json(r).get("network", {}).get("stations", [])
    return {"network": network, "station_count": len(stations),
            "sample": [{"name": s.get("name"), "free_bikes": s.get("free_bikes")}
                       for s in stations[:3]]}


# --- Retail / food / library ----------------------------------------------
def open_food_facts(barcode: str = "737628064502") -> dict:
    """Look up a product by barcode in Open Food Facts (no auth)."""
    r = polite_get(f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json")
    d = _json(r)
    if d.get("status") != 1:
        raise ValueError(f"no Open Food Facts product for barcode {barcode!r}")
    p = d.get("product", {})
    return {"name": p.get("product_name"), "brands": p.get("brands"),
            "nutriscore": p.get("nutriscore_grade")}


def breweries(city: str = "san diego", per_page: int = 3) -> dict:
    """Find breweries in a city via Open Brewery DB (no auth)."""
    r = polite_get("https://api.openbrewerydb.org/v1/breweries", params={
        "by_city": city, "per_page": per_page})
    return {"breweries": [{"name": b.get("name"), "type": b.get("brewery_type")}
                          for b in _json(r)]}


def open_library(query: str = "the pragmatic programmer") -> dict:
    """Search books via Open Library (no auth)."""
    r = polite_get("https://openlibrary.org/search.json", params={"q": query, "limit": 3})
    docs = _json(r).get("docs", [])
    return {"books": [{"title": d.get("title"),
                       "author": (d.get("author_name") or [None])[0],
                       "year": d.get("first_publish_year")} for d in docs]}


def fake_store_products(limit: int = 3) -> dict:
    """Real REST product catalogue (FakeStore API, no auth) — e-commerce data."""
    r = polite_get("https://fakestoreapi.com/products", params={"limit": limit})
    return {"products": [{"title": p.get("title"), "price": p.get("price"),
                          "category": p.get("category")} for p in _json(r)]}


# --- Language / text / news ------------------------------------------------
def define_word(word: str = "serendipity") -> dict:
    """Dictionary definition of a word (Free Dictionary API, no auth)."""
    r = polite_get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}")
    entries = _json(r)
    if not entries:
        raise ValueError(f"no definition for {word!r}")
    meanings = entries[0].get("meanings", [])
    defs = [m["definitions"][0]["definition"] for m in meanings if m.get("definitions")]
    return {"word": word, "definitions": defs[:2]}


def related_words(word: str = "ocean", max_results: int = 8) -> dict:
    """Words related to a term via Datamuse (no auth)."""
    r = polite_get("https://api.datamuse.com/words", params={"ml": word, "max": max_results})
    return {"related": [w.get("word") for w in _json(r)]}


def profanity_filter(text: str) -> dict:
    """Mask profanity in text via PurgoMalum (no auth) — content moderation."""
    r = polite_get("https://www.purgomalum.com/service/json", params={"text": text})
    return _json(r)


def wikipedia_summary(title: str = "Artificial intelligence") -> dict:
    """Plain-text summary of a Wikipedia article (REST API, no auth)."""
    safe = title.replace(" ", "_")
    r = polite_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe}")
    d = _json(r)
    return {"title": d.get("title"), "extract": (d.get("extract") or "")[:400]}


def hacker_news_top(limit: int = 5) -> dict:
    """Current top Hacker News story titles (Firebase API, no auth)."""
    r = polite_get("https://hacker-news.firebaseio.com/v0/topstories.json")
    ids = _json(r)[:limit]
    titles = []
    for sid in ids:
        ir = polite_get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        titles.append(_json(ir).get("title"))
    return {"titles": titles}


# --- Jobs / people / HR ----------------------------------------------------
def remote_jobs(industry: str = "data-science", count: int = 3) -> dict:
    """Live remote job listings via Jobicy (no auth)."""
    r = polite_get("https://jobicy.com/api/v2/remote-jobs", params={
        "count": count, "industry": industry})
    jobs = _json(r).get("jobs", [])
    return {"jobs": [{"title": j.get("jobTitle"), "company": j.get("companyName")}
                     for j in jobs]}


def universities(country: str = "United States", limit: int = 3) -> dict:
    """Universities in a country via the Hipolabs API (no auth)."""
    r = polite_get("http://universities.hipolabs.com/search", params={"country": country})
    data = _json(r)[:limit]
    return {"universities": [u.get("name") for u in data]}


def predict_age(name: str = "alex") -> dict:
    """Predict age from a first name via Agify (no auth) — people enrichment."""
    r = polite_get("https://api.agify.io", params={"name": name})
    return _json(r)


def predict_nationality(name: str = "alessandro") -> dict:
    """Predict likely nationality from a first name via Nationalize (no auth)."""
    r = polite_get("https://api.nationalize.io", params={"name": name})
    d = _json(r)
    return {"name": d.get("name"),
            "countries": [c.get("country_id") for c in d.get("country", [])[:3]]}


# ===========================================================================
# Registry: name -> (callable, properties, required, description)
# Same shape as toolkit.py so the schema/subset/manifest helpers are identical.
# ===========================================================================
def _oai(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


def _ant(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


_S = "string"
_N = "number"
_I = "integer"

_DEFS: dict[str, tuple[Callable, dict, list[str], str]] = {
    "get_weather": (get_weather, {"latitude": {"type": _N}, "longitude": {"type": _N}},
                    ["latitude", "longitude"], "Live current weather at a latitude/longitude (Open-Meteo)."),
    "air_quality": (air_quality, {"latitude": {"type": _N}, "longitude": {"type": _N}},
                    ["latitude", "longitude"], "Live air quality (PM2.5/PM10/ozone/EAQI) at a lat/lon."),
    "carbon_intensity": (carbon_intensity, {}, [], "Current UK electricity grid carbon intensity (gCO2/kWh)."),
    "geocode": (geocode, {"query": {"type": _S}}, ["query"], "Resolve a place name to latitude/longitude (OSM Nominatim)."),
    "zip_lookup": (zip_lookup, {"country": {"type": _S}, "postal_code": {"type": _S}},
                   ["country", "postal_code"], "Look up places for a postal code (Zippopotam.us)."),
    "fx_rate": (fx_rate, {"base": {"type": _S}, "symbols": {"type": _S}}, [],
                "Live FX rates for a base currency (open.er-api.com)."),
    "world_bank_indicator": (world_bank_indicator, {"country": {"type": _S}, "indicator": {"type": _S}}, [],
                             "Latest World Bank indicator value (default GDP, current US$)."),
    "crypto_price": (crypto_price, {"ids": {"type": _S}, "vs": {"type": _S}}, [],
                     "Live crypto spot prices (CoinGecko)."),
    "sec_company_facts": (sec_company_facts, {"cik": {"type": _S}}, ["cik"],
                          "Latest SEC EDGAR 10-K facts (assets/liabilities/revenue) for a CIK."),
    "federal_register": (federal_register, {"term": {"type": _S}, "per_page": {"type": _I}}, [],
                         "Recent US Federal Register document titles matching a term."),
    "iss_position": (iss_position, {}, [], "Current latitude/longitude of the ISS (changes every call)."),
    "recent_earthquakes": (recent_earthquakes, {"min_magnitude": {"type": _N}}, [],
                           "Significant earthquakes in the past day (USGS)."),
    "arxiv_search": (arxiv_search, {"query": {"type": _S}, "max_results": {"type": _I}}, [],
                     "Recent arXiv paper titles matching a query."),
    "crypto_market": (crypto_market, {"coin": {"type": _S}}, [], "24h market stats for a coin (Coinpaprika)."),
    "frankfurter_fx": (frankfurter_fx, {"base": {"type": _S}, "symbols": {"type": _S}}, [],
                       "ECB reference FX rates (Frankfurter)."),
    "usaspending_agency": (usaspending_agency, {"fiscal_year": {"type": _I}}, [],
                           "Top US federal spending agencies for a fiscal year (USAspending)."),
    "fbi_wanted": (fbi_wanted, {"page": {"type": _I}}, [], "Current FBI Wanted listing titles."),
    "country_profile": (country_profile, {"country": {"type": _S}}, [],
                        "Region/capital/income-level + population for a country (World Bank)."),
    "openfda_enforcement": (openfda_enforcement, {"search": {"type": _S}, "limit": {"type": _I}}, [],
                            "Recent FDA drug recall/enforcement reports (openFDA)."),
    "npi_lookup": (npi_lookup, {"npi": {"type": _S}}, [], "Look up a US healthcare provider (NPPES NPI)."),
    "clinical_trials": (clinical_trials, {"condition": {"type": _S}, "limit": {"type": _I}}, [],
                        "Recent ClinicalTrials.gov studies for a condition."),
    "crossref_works": (crossref_works, {"query": {"type": _S}, "rows": {"type": _I}}, [],
                       "Scholarly works matching a query (Crossref)."),
    "upcoming_launches": (upcoming_launches, {"limit": {"type": _I}}, [],
                          "Upcoming orbital rocket launches (Launch Library 2)."),
    "spaceflight_news": (spaceflight_news, {"limit": {"type": _I}}, [], "Latest spaceflight news headlines."),
    "gbif_species": (gbif_species, {"name": {"type": _S}}, [], "Match a species name in the GBIF backbone."),
    "decode_vin": (decode_vin, {"vin": {"type": _S}}, [], "Decode a vehicle VIN (NHTSA vPIC)."),
    "citybikes_network": (citybikes_network, {"network": {"type": _S}}, [],
                          "Live bike-share station availability (CityBikes)."),
    "open_food_facts": (open_food_facts, {"barcode": {"type": _S}}, ["barcode"],
                        "Look up a food product by barcode (Open Food Facts)."),
    "breweries": (breweries, {"city": {"type": _S}, "per_page": {"type": _I}}, [],
                  "Find breweries in a city (Open Brewery DB)."),
    "open_library": (open_library, {"query": {"type": _S}}, [], "Search books (Open Library)."),
    "fake_store_products": (fake_store_products, {"limit": {"type": _I}}, [],
                            "Real REST e-commerce product catalogue (FakeStore)."),
    "define_word": (define_word, {"word": {"type": _S}}, [], "Dictionary definition of a word."),
    "related_words": (related_words, {"word": {"type": _S}, "max_results": {"type": _I}}, [],
                      "Words related to a term (Datamuse)."),
    "profanity_filter": (profanity_filter, {"text": {"type": _S}}, ["text"],
                         "Mask profanity in text (PurgoMalum) — content moderation."),
    "wikipedia_summary": (wikipedia_summary, {"title": {"type": _S}}, [], "Summary of a Wikipedia article."),
    "hacker_news_top": (hacker_news_top, {"limit": {"type": _I}}, [], "Current top Hacker News story titles."),
    "remote_jobs": (remote_jobs, {"industry": {"type": _S}, "count": {"type": _I}}, [],
                    "Live remote job listings (Jobicy)."),
    "universities": (universities, {"country": {"type": _S}, "limit": {"type": _I}}, [],
                     "Universities in a country (Hipolabs)."),
    "predict_age": (predict_age, {"name": {"type": _S}}, [], "Predict age from a first name (Agify)."),
    "predict_nationality": (predict_nationality, {"name": {"type": _S}}, [],
                            "Predict nationality from a first name (Nationalize)."),
}

# name -> callable
TOOL_FUNCTIONS: dict[str, Callable] = {name: d[0] for name, d in _DEFS.items()}


def openai_schemas(names: list[str] | None = None) -> list[dict]:
    """OpenAI function-calling schemas for the named tools (all if None)."""
    names = names or list(_DEFS)
    return [_oai(n, _DEFS[n][3], _DEFS[n][1], _DEFS[n][2]) for n in names]


def anthropic_schemas(names: list[str] | None = None) -> list[dict]:
    """Anthropic tool-use schemas for the named tools (all if None)."""
    names = names or list(_DEFS)
    return [_ant(n, _DEFS[n][3], _DEFS[n][1], _DEFS[n][2]) for n in names]


def subset(names: list[str]) -> dict[str, Callable]:
    """A {name: callable} dict restricted to the named tools."""
    return {n: TOOL_FUNCTIONS[n] for n in names}


def mcp_manifest(names: list[str] | None = None) -> dict:
    """An MCP-style tools/list manifest for the named tools."""
    names = names or list(_DEFS)
    return {"tools": [{"name": n, "description": _DEFS[n][3],
                       "inputSchema": {"type": "object", "properties": _DEFS[n][1],
                                       "required": _DEFS[n][2]}} for n in names]}


# ---------------------------------------------------------------------------
# Manual realness check: call every tool once and print live output.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json_mod

    # A couple of tools need arguments; supply sensible live ones.
    _ARGS: dict[str, dict] = {
        "get_weather": {"latitude": 51.5072, "longitude": -0.1276},   # London
        "air_quality": {"latitude": 51.5072, "longitude": -0.1276},
        "geocode": {"query": "San Francisco"},
        "zip_lookup": {"country": "us", "postal_code": "90210"},
        "sec_company_facts": {"cik": "320193"},   # Apple
        "profanity_filter": {"text": "this damn thing is great"},
    }
    print(f"Calling {len(TOOL_FUNCTIONS)} real tools (User-Agent: {USER_AGENT})\n")
    ok = 0
    for name, fn in TOOL_FUNCTIONS.items():
        try:
            out = fn(**_ARGS.get(name, {}))
            ok += 1
            print(f"  [live] {name}: {_json_mod.dumps(out)[:160]}")
        except Exception as exc:  # noqa: BLE001 - realness probe, show everything
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ok}/{len(TOOL_FUNCTIONS)} tools returned live data. "
          f"Re-run: values (prices, ISS, quakes) will have changed.")
