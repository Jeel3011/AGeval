"""
examples/agents/toolkit.py

A shared library of realistic, production-shaped tools used by the example
agents in this directory. These are the kinds of tools real industry agents
call: HTTP fetches, SQL queries, vector search, payments, calendars,
ticketing, file I/O, code execution, notifications, and so on.

Nothing here is a "toy". Each tool:
  - has a real JSON-schema (OpenAI + Anthropic flavours),
  - does real, deterministic local work (so examples run with zero external
    infra and zero extra cost), and
  - raises realistic exceptions that AGeval's error classifier understands
    (ConnectionError/Timeout -> env_error, ValueError/KeyError -> agent_error).

The point: a marketing/proof claim that "AGeval evaluates real agents with
many tools, MCP servers, and real frameworks" is backed by code that actually
wires those tools into LangGraph, CrewAI, OpenAI, Anthropic, and MCP loops.

The LLM calls in the agent files are REAL. The tools are local so that the
*only* cost of running an example is the model tokens, which keeps a full
sweep cheap and lets a budget guard bound spend precisely.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tiny in-memory "infrastructure" the tools operate against.
# This stands in for a CRM DB, a product catalogue, a vector index, etc.
# ---------------------------------------------------------------------------
_CUSTOMERS = {
    "C-1001": {"name": "Acme Corp", "plan": "enterprise", "mrr": 4200, "open_tickets": 2, "region": "us-east"},
    "C-1002": {"name": "Globex", "plan": "growth", "mrr": 890, "open_tickets": 0, "region": "eu-west"},
    "C-1003": {"name": "Initech", "plan": "starter", "mrr": 49, "open_tickets": 5, "region": "us-west"},
}

_CATALOG = {
    "SKU-RED-TEE": {"title": "Red T-Shirt", "price": 19.99, "stock": 120, "category": "apparel"},
    "SKU-BLU-MUG": {"title": "Blue Mug", "price": 9.50, "stock": 0, "category": "kitchen"},
    "SKU-GRN-CAP": {"title": "Green Cap", "price": 14.00, "stock": 37, "category": "apparel"},
    "SKU-LAPTOP": {"title": "Laptop Stand", "price": 42.00, "stock": 8, "category": "office"},
}

_KB_DOCS = [
    ("How to reset your password", "Go to Settings > Security and click 'Reset password'. A link is emailed to you."),
    ("Refund policy", "Refunds are issued within 30 days of purchase for unused items in original packaging."),
    ("Enterprise SLA", "Enterprise plans include 99.95% uptime, a 1-hour P1 response, and a dedicated CSM."),
    ("Rate limits", "The API allows 600 requests/minute on growth, 6000/minute on enterprise."),
    ("Data residency", "EU-west customers have all data stored in Frankfurt; US data stays in us-east-1."),
    ("Webhook retries", "Failed webhooks retry with exponential backoff for up to 24 hours."),
]

_FX = {("USD", "EUR"): 0.92, ("EUR", "USD"): 1.08, ("USD", "JPY"): 156.0,
       ("JPY", "USD"): 0.0064, ("USD", "GBP"): 0.79, ("GBP", "USD"): 1.27}

_FS: dict[str, str] = {}  # virtual filesystem for the coding/RPA agents


# ---------------------------------------------------------------------------
# A simple, deterministic embedding so "vector search" is real (cosine on
# hashed token frequencies) without needing an embedding API call.
# ---------------------------------------------------------------------------
def _embed(text: str, dim: int = 64) -> list[float]:
    vec = [0.0] * dim
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ===========================================================================
# The tools. Each is a plain Python function with a docstring.
# ===========================================================================
def http_get(url: str) -> dict:
    """Fetch JSON from an internal service URL. Raises on unreachable hosts."""
    if "timeout" in url or "unreachable" in url:
        raise ConnectionError(f"upstream timeout contacting {url}")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"invalid url: {url!r}")
    # Deterministic synthetic payload keyed on the path.
    return {"url": url, "status": 200, "etag": hashlib.md5(url.encode()).hexdigest()[:8],
            "body": {"ok": True, "ts": "2026-06-03T00:00:00Z"}}


def sql_query(query: str) -> list[dict]:
    """Run a read-only SQL query against the customers table."""
    q = query.lower().strip()
    if not q.startswith("select"):
        raise ValueError("only SELECT statements are permitted (read-only role)")
    rows = [{"id": cid, **c} for cid, c in _CUSTOMERS.items()]
    if "where plan" in q:
        m = re.search(r"plan\s*=\s*'([^']+)'", q)
        if m:
            rows = [r for r in rows if r["plan"] == m.group(1)]
    if "order by mrr desc" in q:
        rows.sort(key=lambda r: r["mrr"], reverse=True)
    if "limit 1" in q:
        rows = rows[:1]
    return rows


def get_customer(customer_id: str) -> dict:
    """Look up a single customer record by id."""
    rec = _CUSTOMERS.get(customer_id.strip().upper())
    if rec is None:
        raise KeyError(f"no customer with id {customer_id!r}")
    return {"id": customer_id, **rec}


def vector_search(query: str, k: int = 3) -> list[dict]:
    """Semantic search over the knowledge base. Returns top-k passages."""
    qv = _embed(query)
    scored = [(t, b, _cosine(qv, _embed(t + " " + b))) for t, b in _KB_DOCS]
    scored.sort(key=lambda x: x[2], reverse=True)
    return [{"title": t, "snippet": b, "score": round(s, 4)} for t, b, s in scored[: max(1, int(k))]]


def get_product(sku: str) -> dict:
    """Fetch a product from the catalogue by SKU."""
    rec = _CATALOG.get(sku.strip().upper())
    if rec is None:
        raise KeyError(f"unknown SKU {sku!r}")
    return {"sku": sku, **rec}


def check_inventory(sku: str) -> dict:
    """Return current stock level and whether the item is purchasable."""
    p = get_product(sku)
    return {"sku": sku, "stock": p["stock"], "in_stock": p["stock"] > 0}


def create_order(sku: str, quantity: int) -> dict:
    """Place an order. Fails if quantity exceeds stock."""
    qty = int(quantity)
    if qty <= 0:
        raise ValueError("quantity must be positive")
    p = get_product(sku)
    if qty > p["stock"]:
        raise ValueError(f"insufficient stock for {sku}: have {p['stock']}, requested {qty}")
    return {"order_id": "ORD-" + hashlib.md5(f"{sku}{qty}".encode()).hexdigest()[:8],
            "sku": sku, "quantity": qty, "total": round(p["price"] * qty, 2), "status": "confirmed"}


def process_payment(amount: float, currency: str = "USD", method: str = "card") -> dict:
    """Charge a payment method. Declines amounts over the synthetic limit."""
    amt = float(amount)
    if amt <= 0:
        raise ValueError("amount must be positive")
    if amt > 10000:
        raise ValueError("amount exceeds single-transaction limit")
    if method not in {"card", "ach", "wire"}:
        raise ValueError(f"unsupported payment method {method!r}")
    return {"charge_id": "ch_" + hashlib.md5(f"{amt}{currency}".encode()).hexdigest()[:10],
            "amount": round(amt, 2), "currency": currency.upper(), "method": method, "status": "captured"}


def currency_convert(amount: float, from_ccy: str, to_ccy: str) -> dict:
    """Convert an amount between currencies using current FX rates."""
    f, t = from_ccy.upper(), to_ccy.upper()
    if f == t:
        return {"amount": round(float(amount), 2), "currency": t}
    rate = _FX.get((f, t))
    if rate is None:
        raise ValueError(f"no FX rate for {f}->{t}")
    return {"amount": round(float(amount) * rate, 2), "currency": t, "rate": rate}


def calculate(expression: str) -> float:
    """Evaluate a basic arithmetic expression. No names/builtins allowed."""
    if not set(expression) <= set("0123456789+-*/(). %"):
        raise ValueError("expression contains unsupported characters")
    return float(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307


def get_weather(city: str) -> dict:
    """Return current weather for a city (deterministic synthetic data)."""
    table = {"tokyo": (22, "sunny"), "paris": (14, "rainy"), "london": (12, "cloudy"),
             "new york": (18, "clear"), "berlin": (10, "overcast")}
    temp, cond = table.get(city.lower().strip(), (20, "clear"))
    return {"city": city, "temp_c": temp, "condition": cond}


def geocode(address: str) -> dict:
    """Resolve a free-form address to lat/lng (synthetic but stable)."""
    if not address.strip():
        raise ValueError("address is empty")
    h = int(hashlib.md5(address.lower().encode()).hexdigest(), 16)
    return {"address": address, "lat": round((h % 18000) / 100 - 90, 4),
            "lng": round((h % 36000) / 100 - 180, 4)}


def search_flights(origin: str, destination: str, date: str) -> list[dict]:
    """Search flights between two airports on a date."""
    if origin.upper() == destination.upper():
        raise ValueError("origin and destination must differ")
    base = (int(hashlib.md5((origin + destination).encode()).hexdigest(), 16) % 400) + 120
    return [{"flight": f"AA{100 + i}", "origin": origin.upper(), "destination": destination.upper(),
             "date": date, "price_usd": base + i * 35, "stops": i} for i in range(3)]


def book_calendar(title: str, start_iso: str, duration_min: int = 30) -> dict:
    """Create a calendar event. Validates the timestamp."""
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid start time {start_iso!r}: {exc}") from exc
    end = start + timedelta(minutes=int(duration_min))
    return {"event_id": "evt_" + hashlib.md5(title.encode()).hexdigest()[:8],
            "title": title, "start": start.isoformat(), "end": end.isoformat()}


def send_email(to: str, subject: str, body: str) -> dict:
    """Send a transactional email. Validates the recipient address."""
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
        raise ValueError(f"invalid recipient address {to!r}")
    return {"message_id": "msg_" + hashlib.md5((to + subject).encode()).hexdigest()[:10],
            "to": to, "subject": subject, "queued": True}


def post_slack(channel: str, text: str) -> dict:
    """Post a message to a Slack channel via the (synthetic) Slack API."""
    if not channel.startswith("#"):
        raise ValueError("channel must start with '#'")
    return {"channel": channel, "ts": str(time.time()), "ok": True, "chars": len(text)}


def create_ticket(subject: str, priority: str = "P3") -> dict:
    """Open a support ticket in the ticketing system."""
    if priority not in {"P1", "P2", "P3", "P4"}:
        raise ValueError(f"invalid priority {priority!r}")
    return {"ticket_id": "TCK-" + hashlib.md5(subject.encode()).hexdigest()[:6].upper(),
            "subject": subject, "priority": priority, "status": "open"}


def read_file(path: str) -> str:
    """Read a file from the agent's virtual workspace."""
    if path not in _FS:
        raise FileNotFoundError(f"no such file: {path}")
    return _FS[path]


def write_file(path: str, content: str) -> dict:
    """Write a file into the agent's virtual workspace."""
    _FS[path] = content
    return {"path": path, "bytes": len(content.encode())}


def run_python(code: str) -> dict:
    """Execute a small, sandboxed Python snippet and capture the result."""
    if any(bad in code for bad in ("import os", "import sys", "open(", "__import__", "subprocess")):
        raise ValueError("disallowed operation in sandboxed code")
    scope: dict[str, Any] = {}
    try:
        exec(code, {"__builtins__": {"range": range, "len": len, "sum": sum, "min": min, "max": max}}, scope)  # noqa: S102
    except Exception as exc:  # surface as agent_error
        raise ValueError(f"code raised {type(exc).__name__}: {exc}") from exc
    return {"locals": {k: _jsonable(v) for k, v in scope.items() if not k.startswith("_")}}


def flaky_inventory_service(item: str) -> str:
    """A deliberately unreliable upstream — always times out. Used to prove
    that AGeval captures and classifies env_errors on real runs."""
    raise ConnectionError("upstream timeout contacting legacy inventory service")


def _jsonable(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


# ===========================================================================
# Registry: name -> (callable, openai_schema, anthropic_schema)
# This is the single source of truth every agent file imports from. It also
# mirrors how an MCP server would advertise its tools.
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

# (fn, properties, required, description)
_DEFS: dict[str, tuple[Callable, dict, list[str], str]] = {
    "http_get": (http_get, {"url": {"type": _S}}, ["url"], "Fetch JSON from an internal service URL."),
    "sql_query": (sql_query, {"query": {"type": _S}}, ["query"], "Run a read-only SQL SELECT against the customers table."),
    "get_customer": (get_customer, {"customer_id": {"type": _S}}, ["customer_id"], "Look up a customer by id."),
    "vector_search": (vector_search, {"query": {"type": _S}, "k": {"type": _I}}, ["query"], "Semantic search over the knowledge base."),
    "get_product": (get_product, {"sku": {"type": _S}}, ["sku"], "Fetch a product from the catalogue by SKU."),
    "check_inventory": (check_inventory, {"sku": {"type": _S}}, ["sku"], "Return current stock level for a SKU."),
    "create_order": (create_order, {"sku": {"type": _S}, "quantity": {"type": _I}}, ["sku", "quantity"], "Place an order for a SKU."),
    "process_payment": (process_payment, {"amount": {"type": _N}, "currency": {"type": _S}, "method": {"type": _S}}, ["amount"], "Charge a payment method."),
    "currency_convert": (currency_convert, {"amount": {"type": _N}, "from_ccy": {"type": _S}, "to_ccy": {"type": _S}}, ["amount", "from_ccy", "to_ccy"], "Convert an amount between currencies."),
    "calculate": (calculate, {"expression": {"type": _S}}, ["expression"], "Evaluate a basic arithmetic expression."),
    "get_weather": (get_weather, {"city": {"type": _S}}, ["city"], "Current weather for a city."),
    "geocode": (geocode, {"address": {"type": _S}}, ["address"], "Resolve an address to latitude/longitude."),
    "search_flights": (search_flights, {"origin": {"type": _S}, "destination": {"type": _S}, "date": {"type": _S}}, ["origin", "destination", "date"], "Search flights between two airports."),
    "book_calendar": (book_calendar, {"title": {"type": _S}, "start_iso": {"type": _S}, "duration_min": {"type": _I}}, ["title", "start_iso"], "Create a calendar event."),
    "send_email": (send_email, {"to": {"type": _S}, "subject": {"type": _S}, "body": {"type": _S}}, ["to", "subject", "body"], "Send a transactional email."),
    "post_slack": (post_slack, {"channel": {"type": _S}, "text": {"type": _S}}, ["channel", "text"], "Post a message to a Slack channel."),
    "create_ticket": (create_ticket, {"subject": {"type": _S}, "priority": {"type": _S}}, ["subject"], "Open a support ticket."),
    "read_file": (read_file, {"path": {"type": _S}}, ["path"], "Read a file from the workspace."),
    "write_file": (write_file, {"path": {"type": _S}, "content": {"type": _S}}, ["path", "content"], "Write a file to the workspace."),
    "run_python": (run_python, {"code": {"type": _S}}, ["code"], "Execute a small sandboxed Python snippet."),
    "flaky_inventory_service": (flaky_inventory_service, {"item": {"type": _S}}, ["item"], "Look up an item in the (unreliable) legacy inventory service."),
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
    """An MCP-style tools/list manifest for the named tools. This is exactly
    the shape an MCP server returns from a `tools/list` request."""
    names = names or list(_DEFS)
    return {"tools": [{"name": n, "description": _DEFS[n][3],
                       "inputSchema": {"type": "object", "properties": _DEFS[n][1],
                                       "required": _DEFS[n][2]}} for n in names]}
