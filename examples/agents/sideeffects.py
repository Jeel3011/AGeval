"""
examples/agents/sideeffects.py

**Real side-effecting tools** for the AGeval fleet, with an honest
credential gate. These are the tools that *change the world*: write a row to a
real database, mint a real short link, render a real QR code, POST to a real
webhook, send a real email / Slack message.

Two layers of safety, by design:

1. **Master gate** — every side-effecting tool is inert unless
   `AGEVAL_LIVE_SIDE_EFFECTS=1`. A read-only fleet sweep therefore never mutates
   anything by accident; each tool returns ``{"skipped": "...", "gated": True}``.

2. **Per-tool credential gate** — tools that need a provider key check for it
   and, when absent, return ``{"needs": "<ENV_VAR>", ...}`` instead of faking a
   send. This is the same "report `needs <KEY>`" contract the framework example
   agents already use. Nothing here is ever simulated: a tool either performs
   the real effect or honestly reports what it would need.

Capability matrix (what is real *today* vs. what activates on a dropped key):

    Tool                 Real today?  Needs
    db_write             yes          AGEVAL_SUPABASE_SERVICE_KEY (+ URL)   [present]
    short_link           yes          nothing (is.gd, no auth)
    make_qr              yes          nothing (goQR, no auth)
    post_webhook         yes          a target URL passed as an argument
    send_email           gated        RESEND_API_KEY
    post_slack           gated        SLACK_WEBHOOK_URL

The public surface (TOOL_FUNCTIONS / openai_schemas / anthropic_schemas /
subset / mcp_manifest) matches toolkit.py and real_tools.py exactly, so these
tools compose into the same agent loops.

Errors map onto AGeval's classifier like everything else: transport/timeout →
ConnectionError (env_error); bad input / missing-but-required → ValueError
(agent_error). A *gated* return is not an error — the agent gets a normal tool
result describing the gate, which is itself realistic agent behaviour.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from examples.agents.real_tools import (
    _I,
    _S,
    _ant,
    _oai,
    polite_get,
    polite_post,
)


def live_side_effects_enabled() -> bool:
    return os.environ.get("AGEVAL_LIVE_SIDE_EFFECTS") == "1"


def _gated() -> dict:
    return {"gated": True,
            "skipped": "side effects disabled — set AGEVAL_LIVE_SIDE_EFFECTS=1 to perform real effects"}


# ===========================================================================
# Real-today side effects
# ===========================================================================
def db_write(table: str, payload: dict | None = None, note: str = "") -> dict:
    """Insert a real row into a Supabase table (default: fleet_side_effects).
    Real when AGEVAL_SUPABASE_URL + AGEVAL_SUPABASE_SERVICE_KEY are set."""
    if not live_side_effects_enabled():
        return _gated()
    url = os.environ.get("AGEVAL_SUPABASE_URL")
    key = os.environ.get("AGEVAL_SUPABASE_SERVICE_KEY")
    if not url or not key:
        return {"needs": "AGEVAL_SUPABASE_SERVICE_KEY", "table": table}
    table = table or "fleet_side_effects"
    row = {"note": note or "ageval fleet side effect", "payload": payload or {}}
    try:
        from supabase import create_client
        client = create_client(url, key)
        res = client.table(table).insert(row).execute()
    except Exception as exc:  # network / auth / missing-table -> surface honestly
        # PostgREST returns a 4xx for an unknown table; treat as agent_error.
        raise ValueError(f"db_write to {table!r} failed: {type(exc).__name__}: {exc}") from exc
    data = getattr(res, "data", None)
    return {"inserted": True, "table": table, "rows": len(data) if data else 0,
            "id": (data[0].get("id") if data else None)}


def short_link(url: str) -> dict:
    """Create a real is.gd short link for a URL (no auth)."""
    if not live_side_effects_enabled():
        return _gated()
    if not url.startswith(("http://", "https://")):
        raise ValueError("short_link requires an absolute http(s) URL")
    r = polite_get("https://is.gd/create.php", params={"format": "json", "url": url})
    data = r.json()
    if "shorturl" not in data:
        raise ValueError(f"is.gd error: {data.get('errormessage', data)}")
    return {"short_url": data["shorturl"], "long_url": url}


def make_qr(text: str, size: int = 200) -> dict:
    """Render a real QR code PNG for `text` via goQR (no auth). Returns the
    image URL and its byte size (the image is really fetched)."""
    if not live_side_effects_enabled():
        return _gated()
    img_url = "https://api.qrserver.com/v1/create-qr-code/"
    r = polite_get(img_url, params={"size": f"{size}x{size}", "data": text})
    return {"image_url": f"{img_url}?size={size}x{size}&data={text}",
            "content_type": r.headers.get("Content-Type"), "bytes": len(r.content)}


def post_webhook(target_url: str, payload: dict | None = None) -> dict:
    """POST a JSON payload to a real outbound webhook URL (e.g. a webhook.site
    or RequestBin endpoint the operator controls). No auth — the URL is the
    capability."""
    if not live_side_effects_enabled():
        return _gated()
    if not target_url.startswith(("http://", "https://")):
        raise ValueError("post_webhook requires an absolute http(s) target URL")
    r = polite_post(target_url, json=payload or {"source": "ageval-fleet"})
    return {"posted": True, "status": r.status_code, "target": target_url}


# ===========================================================================
# Credential-gated side effects (read/build path runs; the *send* needs a key)
# ===========================================================================
def send_email(to: str, subject: str, body: str) -> dict:
    """Send a real transactional email via Resend. Needs RESEND_API_KEY; until
    set, reports the gate honestly (no fake send)."""
    if not live_side_effects_enabled():
        return _gated()
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return {"needs": "RESEND_API_KEY", "would_send": {"to": to, "subject": subject}}
    sender = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    r = polite_post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"from": sender, "to": [to], "subject": subject, "text": body})
    return {"sent": True, "id": r.json().get("id"), "to": to}


def post_slack(text: str, channel: str = "") -> dict:
    """Post a real message to Slack via an Incoming Webhook. Needs
    SLACK_WEBHOOK_URL; until set, reports the gate honestly."""
    if not live_side_effects_enabled():
        return _gated()
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if not hook:
        return {"needs": "SLACK_WEBHOOK_URL", "would_post": {"channel": channel, "text": text}}
    payload: dict[str, Any] = {"text": text}
    if channel:
        payload["channel"] = channel
    r = polite_post(hook, json=payload)
    return {"posted": True, "status": r.status_code}


# ===========================================================================
# Registry — same shape as toolkit.py / real_tools.py.
# ===========================================================================
_DEFS: dict[str, tuple[Callable, dict, list[str], str]] = {
    "db_write": (db_write, {"table": {"type": _S}, "payload": {"type": "object"}, "note": {"type": _S}},
                 ["table"], "Insert a real row into a Supabase table (real side effect)."),
    "short_link": (short_link, {"url": {"type": _S}}, ["url"],
                   "Create a real is.gd short link for a URL."),
    "make_qr": (make_qr, {"text": {"type": _S}, "size": {"type": _I}}, ["text"],
                "Render a real QR-code image for some text (goQR)."),
    "post_webhook": (post_webhook, {"target_url": {"type": _S}, "payload": {"type": "object"}},
                     ["target_url"], "POST a JSON payload to a real outbound webhook URL."),
    "send_email": (send_email, {"to": {"type": _S}, "subject": {"type": _S}, "body": {"type": _S}},
                   ["to", "subject", "body"], "Send a real transactional email (needs RESEND_API_KEY)."),
    "post_slack": (post_slack, {"text": {"type": _S}, "channel": {"type": _S}}, ["text"],
                   "Post a real Slack message via Incoming Webhook (needs SLACK_WEBHOOK_URL)."),
}

TOOL_FUNCTIONS: dict[str, Callable] = {name: d[0] for name, d in _DEFS.items()}


def openai_schemas(names: list[str] | None = None) -> list[dict]:
    names = names or list(_DEFS)
    return [_oai(n, _DEFS[n][3], _DEFS[n][1], _DEFS[n][2]) for n in names]


def anthropic_schemas(names: list[str] | None = None) -> list[dict]:
    names = names or list(_DEFS)
    return [_ant(n, _DEFS[n][3], _DEFS[n][1], _DEFS[n][2]) for n in names]


def subset(names: list[str]) -> dict[str, Callable]:
    return {n: TOOL_FUNCTIONS[n] for n in names}


def mcp_manifest(names: list[str] | None = None) -> dict:
    names = names or list(_DEFS)
    return {"tools": [{"name": n, "description": _DEFS[n][3],
                       "inputSchema": {"type": "object", "properties": _DEFS[n][1],
                                       "required": _DEFS[n][2]}} for n in names]}


def capability_report() -> dict:
    """A snapshot of which side effects are live right now vs. gated."""
    return {
        "master_gate": "on" if live_side_effects_enabled() else "off (AGEVAL_LIVE_SIDE_EFFECTS != 1)",
        "db_write": "real" if os.environ.get("AGEVAL_SUPABASE_SERVICE_KEY") else "needs AGEVAL_SUPABASE_SERVICE_KEY",
        "short_link": "real (no auth)",
        "make_qr": "real (no auth)",
        "post_webhook": "real (target URL is the capability)",
        "send_email": "real" if os.environ.get("RESEND_API_KEY") else "needs RESEND_API_KEY",
        "post_slack": "real" if os.environ.get("SLACK_WEBHOOK_URL") else "needs SLACK_WEBHOOK_URL",
    }


if __name__ == "__main__":
    import json

    import examples.agents._common  # noqa: F401 - importing loads .env via dotenv
    print("Side-effect capability report:")
    print(json.dumps(capability_report(), indent=2))
    if live_side_effects_enabled():
        print("\nMaster gate ON — exercising the no-auth real effects:")
        for name, args in [("short_link", {"url": "https://example.com/ageval-fleet"}),
                           ("make_qr", {"text": "ageval-fleet"})]:
            try:
                print(f"  [live] {name}: {json.dumps(TOOL_FUNCTIONS[name](**args))[:160]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    else:
        print("\nMaster gate OFF — set AGEVAL_LIVE_SIDE_EFFECTS=1 to perform real effects.")
