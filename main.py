"""
main.py

Thin ingestion + query API. This is the only server users talk to.
They never touch Supabase or LangSmith directly.

Endpoints (ingestion — requires API key):
    POST /episodes       — create a stub episode row
    POST /steps          — write one episode_step row
    POST /steps/batch    — write multiple steps in one request
    POST /jobs           — push one episode_job (triggers merger worker)

Endpoints (query — requires API key):
    GET  /episodes                   — list episodes for the authenticated user
    GET  /episodes/{episode_id}      — get one episode with its steps and score
    GET  /episodes/{episode_id}/steps — get all steps for an episode
    GET  /similar                    — find episodes similar to a given one (pgvector)

Utility:
    GET  /health                     — liveness probe (no auth)

Auth:
    Every request must include header:  Authorization: Bearer ageval-sk-<key>
    The raw key is hashed (sha256) and looked up in api_keys table.
    If not found or inactive → 401.
    user_id is extracted from the key and used to scope all data reads/writes.

Run locally:
    uvicorn main:app --reload

Env vars needed on YOUR server (not the user's):
    AGEVAL_SUPABASE_URL
    AGEVAL_SUPABASE_SERVICE_KEY
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from rate_limiter import get_rate_limiter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured logging — JSON in production, human-readable in dev
# ---------------------------------------------------------------------------
_log_format = os.environ.get("LOG_FORMAT", "text").lower()
if _log_format == "json":
    import json as _json

    class _JSONFormatter(logging.Formatter):
        def format(self, record):
            return _json.dumps({
                "ts"     : self.formatTime(record, self.datefmt),
                "level"  : record.levelname,
                "logger" : record.name,
                "msg"    : record.getMessage(),
                "module" : record.module,
                "line"   : record.lineno,
            })

    _handler = logging.StreamHandler()
    _handler.setFormatter(_JSONFormatter())
    logging.root.handlers = [_handler]
    logging.root.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

app = FastAPI(title="ageval ingestion API", version="0.3.0")

# ---------------------------------------------------------------------------
# Global exception handler — NEVER leak stack traces to clients
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return a sanitized error response."""
    _inc_metric("errors_total")
    log.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs for details."},
    )

_cors_origins = os.environ.get("AGEVAL_CORS_ORIGINS", "").strip()
if not _cors_origins:
    log.warning(
        "AGEVAL_CORS_ORIGINS not set — defaulting to '*' (allow all origins). "
        "Set AGEVAL_CORS_ORIGINS to restrict in production."
    )
    _cors_origins = "*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins.split(","),
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Lightweight metrics — in-process counters
# ---------------------------------------------------------------------------
import threading as _threading

_metrics = {"requests_total": 0, "requests_rate_limited": 0, "errors_total": 0}
_metrics_lock = _threading.Lock()


def _inc_metric(name: str) -> None:
    with _metrics_lock:
        _metrics[name] = _metrics.get(name, 0) + 1


# ---------------------------------------------------------------------------
# Rate Limiting Middleware
# ---------------------------------------------------------------------------
# Keyed by API key (extracted from Authorization header) so the limit is
# per-user, not per-IP. Falls back to IP if no key is present (e.g. /health).
# Backend: Redis if REDIS_URL is set, in-memory otherwise.
# Config: RATE_LIMIT_REQUESTS (default 100) / RATE_LIMIT_WINDOW (default 60s)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    _inc_metric("requests_total")

    # Extract rate-limit key: prefer API key, fall back to IP
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        rate_key = f"apikey:{auth.removeprefix('Bearer ').strip()[:16]}"  # prefix only — never log full key
    else:
        rate_key = f"ip:{request.client.host if request.client else 'unknown'}"

    limiter = get_rate_limiter()
    if not limiter.is_allowed(rate_key):
        _inc_metric("requests_rate_limited")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests"},
            headers={"X-RateLimit-Remaining": "0"},
        )

    response = await call_next(request)
    remaining = limiter.remaining(rate_key)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if response.status_code >= 500:
        _inc_metric("errors_total")
    return response


# ---------------------------------------------------------------------------
# Supabase client — module-level singleton
# ---------------------------------------------------------------------------
def _make_client():
    url = os.environ.get("AGEVAL_SUPABASE_URL")
    key = os.environ.get("AGEVAL_SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("AGEVAL_SUPABASE_URL and AGEVAL_SUPABASE_SERVICE_KEY must be set")
    from supabase import create_client
    return create_client(url, key)


_supabase = None


def get_db():
    global _supabase
    if _supabase is None:
        _supabase = _make_client()
    return _supabase


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# Supabase anon key + URL for verifying dashboard JWTs (humans signed in with
# email/password). The browser holds the same anon key; verification happens by
# asking Supabase who the token belongs to. Service key is never used here.
_SUPABASE_ANON_KEY = os.environ.get("AGEVAL_SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY")

# Tiny in-process cache so we don't call Supabase /auth/v1/user on every request
# for the same token. token -> (user_id, expiry_epoch).
_jwt_cache: dict[str, tuple[str, float]] = {}
_JWT_CACHE_TTL = 300  # seconds


def _verify_supabase_jwt(token: str) -> str | None:
    """Resolve a Supabase access token to its user UID, or None if invalid.

    Verifies by calling the project's /auth/v1/user endpoint with the token.
    Cached briefly to bound network calls. Returns None (not raise) so the
    caller can fall through to API-key auth.
    """
    if not _SUPABASE_ANON_KEY:
        return None

    import time
    now = time.time()
    cached = _jwt_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]

    url = os.environ.get("AGEVAL_SUPABASE_URL")
    if not url:
        return None

    try:
        import urllib.request
        req = urllib.request.Request(
            f"{url}/auth/v1/user",
            headers={"apikey": _SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json as _json
            data = _json.loads(resp.read().decode())
        uid = data.get("id")
        if not uid:
            return None
        user_id = f"sb_{uid}"
        _jwt_cache[token] = (user_id, now + _JWT_CACHE_TTL)
        return user_id
    except Exception as exc:
        log.debug(f"Supabase JWT verification failed: {exc}")
        return None


def _verify_ageval_key(raw_key: str) -> str | None:
    """Resolve an `ageval-sk-…` API key to its user_id, or None if invalid."""
    key_hash = _hash_key(raw_key)
    db = get_db()
    resp = (
        db.table("api_keys")
        .select("id, user_id, expires_at")
        .eq("key_hash", key_hash)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None

    row = resp.data[0]
    if row.get("expires_at"):
        expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired. Use POST /keys/rotate to get a new key.",
            )

    # Record last_used_at (best-effort — don't fail auth if this update fails)
    try:
        db.table("api_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", row["id"]).execute()
    except Exception as exc:
        log.warning(f"Could not update last_used_at for key {row['id']}: {exc}")

    return row["user_id"]


def verify_api_key(authorization: str = Header(...)) -> str:
    """
    Auth dependency accepting EITHER credential and resolving both to a user_id:

      • a dashboard session — a Supabase JWT from an email/password login
        (token does NOT start with 'ageval-sk-'); user_id = 'sb_<uid>'.
      • an agent API key — an `ageval-sk-…` key issued from the dashboard,
        used by the SDK for ingestion.

    Returns user_id on success, raises 401 on failure.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    token = authorization.removeprefix("Bearer ").strip()

    # AGeval keys have a fixed prefix; everything else is treated as a JWT.
    if token.startswith("ageval-sk-"):
        user_id = _verify_ageval_key(token)
        if user_id:
            return user_id
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key")

    # Dashboard JWT path.
    user_id = _verify_supabase_jwt(token)
    if user_id:
        return user_id

    # Last resort: maybe it's an API key without the prefix (legacy keys).
    user_id = _verify_ageval_key(token)
    if user_id:
        return user_id

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session/key")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]{1,128}$')


def _validate_id(value: str, field_name: str) -> str:
    """Validate that an ID field matches the allowed pattern."""
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be 1-128 alphanumeric characters, hyphens, underscores, or dots"
        )
    return value


class EpisodeCreate(BaseModel):
    episode_id: str
    agent_id  : str
    task      : str | None = None

    @field_validator('episode_id')
    @classmethod
    def check_episode_id(cls, v: str) -> str:
        return _validate_id(v, 'episode_id')

    @field_validator('agent_id')
    @classmethod
    def check_agent_id(cls, v: str) -> str:
        return _validate_id(v, 'agent_id')


def _generate_embedding(text: str) -> list[float] | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        oc = OpenAI(api_key=api_key)
        resp = oc.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding
    except Exception as exc:
        log.error(f"Embedding generation failed: {exc}")
        return None


class StepCreate(BaseModel):
    episode_id     : str
    step_index     : int
    tool_name      : str
    tool_input     : Any | None = None   # accepts dict, str, list, int — any JSON value
    tool_output    : Any | None = None   # accepts dict, str, list, int — any JSON value
    success        : bool
    error_message  : str | None = None
    error_category : str | None = None   # 'agent_error' | 'env_error' | 'unknown'
    is_recoverable : bool | None = None
    reasoning      : str | None = None
    latency_ms     : int | None = None

    @field_validator('episode_id')
    @classmethod
    def check_episode_id(cls, v: str) -> str:
        return _validate_id(v, 'episode_id')


class EvaluateRequest(BaseModel):
    """A live, in-the-loop verdict request (LIVE_EVAL_WEDGE_PLAN §1).

    Sent BEFORE a tool runs so the agent can act on the verdict. Unlike
    /steps (fire-and-forget telemetry), this is request/response and returns an
    actionable `action` scored against the agent's evaluation memory.
    """
    agent_id     : str
    tool_name    : str
    tool_input   : Any | None = None
    reasoning    : str | None = None
    tools_so_far : list[str] | None = None  # tool names already run this episode
    episode_id   : str | None = None
    step_index   : int | None = None

    @field_validator('agent_id')
    @classmethod
    def check_agent_id(cls, v: str) -> str:
        return _validate_id(v, 'agent_id')


class JobCreate(BaseModel):
    episode_id: str
    run_id    : str          # LangSmith run ID — pass "none" if not using LangSmith
    agent_id  : str
    task      : str | None = None

    @field_validator('episode_id')
    @classmethod
    def check_episode_id(cls, v: str) -> str:
        return _validate_id(v, 'episode_id')

    @field_validator('agent_id')
    @classmethod
    def check_agent_id(cls, v: str) -> str:
        return _validate_id(v, 'agent_id')


class RegisterRequest(BaseModel):
    label: str | None = "default"


class WebhookCreate(BaseModel):
    url      : str
    threshold: float = 0.7


# ---------------------------------------------------------------------------
# SSRF-safe webhook URL validator
# ---------------------------------------------------------------------------
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_webhook_url(url: str) -> None:
    """
    Raises HTTPException(400) if the URL points to a private/internal IP range
    (SSRF protection) or uses a non-https scheme.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise HTTPException(status_code=400, detail="Webhook URL must use http or https scheme")
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Webhook URL has no valid hostname")
    try:
        addr_str = socket.gethostbyname(hostname)
        addr = ipaddress.ip_address(addr_str)
        for network in _PRIVATE_RANGES:
            if addr in network:
                raise HTTPException(
                    status_code=400,
                    detail=f"Webhook URL resolves to a private/internal IP address ({addr_str}) — not allowed",
                )
    except HTTPException:
        raise
    except Exception:
        # DNS resolution failed — reject to be safe
        raise HTTPException(status_code=400, detail=f"Webhook URL hostname could not be resolved: {hostname}")


# ---------------------------------------------------------------------------
# Endpoints — utility & onboarding
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": "0.3.0"}


@app.get("/metrics")
def metrics():
    """
    Basic operational metrics for monitoring.
    Returns request counts and rate limiter stats.
    No authentication required (standard for metrics endpoints).
    """
    limiter = get_rate_limiter()
    with _metrics_lock:
        return {
            "requests_total"       : _metrics["requests_total"],
            "requests_rate_limited": _metrics["requests_rate_limited"],
            "errors_total"         : _metrics["errors_total"],
            "rate_limiter_backend" : type(limiter).__name__,
        }


ADMIN_SECRET = os.environ.get("AGEVAL_ADMIN_SECRET")  # NO default — must be explicitly set


@app.post("/drain")
async def drain(
    x_admin_secret: str = Header(None, description="Admin secret required to trigger a drain"),
):
    """
    Process all pending episode_jobs and return.

    This replaces the always-on merger worker for free/serverless hosting:
    an external scheduler (e.g. cron-job.org) POSTs here every ~60s with the
    admin secret, and we drain the queue once. No 24/7 process required.

    SECURITY: disabled unless AGEVAL_ADMIN_SECRET is set; requires it in the
    X-Admin-Secret header. Safe to call concurrently — pick_job uses
    SELECT ... FOR UPDATE SKIP LOCKED so overlapping drains never double-process.
    """
    if not ADMIN_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Drain is disabled. AGEVAL_ADMIN_SECRET is not configured on this server.",
        )
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")

    from merger.worker import drain_once
    # drain_once is blocking (sync Supabase + scoring), so run it off the event loop.
    import anyio
    result = await anyio.to_thread.run_sync(drain_once)
    return result


@app.post("/register", status_code=201)
def register(
    body: RegisterRequest,
    x_admin_secret: str = Header(None, description="Admin secret required for registration"),
):
    """
    Admin-only API key generation.

    SECURITY: This endpoint is disabled if AGEVAL_ADMIN_SECRET is not set in the environment.
    Never deploy without setting this env var to a strong random secret.
    """
    if not ADMIN_SECRET:
        raise HTTPException(
            status_code=403,
            detail="Registration is disabled. AGEVAL_ADMIN_SECRET is not configured on this server.",
        )
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    db = get_db()
    import secrets
    import uuid
    # Generate a cryptographically secure key (48 hex chars = 192 bits of entropy)
    raw_key = f"ageval-sk-{secrets.token_hex(24)}"
    key_hash = _hash_key(raw_key)
    user_id = f"usr_{uuid.uuid4().hex[:16]}"

    try:
        db.table("api_keys").insert({
            "key_hash": key_hash,
            "user_id" : user_id,
            "label"   : body.label or "",
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info(f"API key issued for user={user_id} label='{body.label}'")
    return {"api_key": raw_key, "user_id": user_id}


# ---------------------------------------------------------------------------
# Endpoints — ingestion
# ---------------------------------------------------------------------------
@app.post("/episodes", status_code=201)
def create_episode(
    body   : EpisodeCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Create a stub episode row before the agent run starts.
    The SDK calls this once at the beginning of each run.
    episode_steps has a FK to episodes, so this must exist first.
    """
    db = get_db()
    try:
        db.table("episodes").insert({
            "episode_id": body.episode_id,
            "agent_id"  : body.agent_id,
            "user_id"   : user_id,
            "run_id"    : "pending",
            "task"      : body.task,
        }).execute()
    except Exception as e:
        # Duplicate episode_id — idempotent, not an error
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return {"episode_id": body.episode_id, "created": False}
        raise HTTPException(status_code=500, detail=str(e))

    return {"episode_id": body.episode_id, "created": True}


@app.post("/steps", status_code=201)
def create_step(
    body   : StepCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Write one episode_step. Called by the SDK after every tool call.
    """
    db = get_db()
    _assert_episode_owned(db, body.episode_id, user_id)

    record = {
        "episode_id"    : body.episode_id,
        "step_index"    : body.step_index,
        "tool_name"     : body.tool_name,
        "tool_input"    : body.tool_input,
        "tool_output"   : body.tool_output,
        "success"       : body.success,
        "error_message" : body.error_message,
        "error_category": body.error_category,
        "is_recoverable": body.is_recoverable,
        "reasoning"     : body.reasoning,
        "latency_ms"    : body.latency_ms,
        "created_at"    : datetime.now(timezone.utc).isoformat(),
    }

    try:
        db.table("episode_steps").insert(record).execute()
    except Exception as e:
        log.error(f"step insert failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@app.post("/steps/batch", status_code=201)
def create_steps_batch(
    body   : list[StepCreate],
    user_id: str = Depends(verify_api_key),
):
    """
    Write multiple episode_steps in one request.
    Called by the SDK when batch=True is set on EpisodeSession,
    or when the SDK flushes a BufferedStepWriter.
    All steps must belong to episodes owned by the authenticated user.
    """
    if not body:
        return {"ok": True, "inserted": 0}

    db = get_db()

    # Verify ownership for all unique episode_ids in the batch
    unique_episodes = {s.episode_id for s in body}
    for eid in unique_episodes:
        _assert_episode_owned(db, eid, user_id)

    records = [
        {
            "episode_id"    : s.episode_id,
            "step_index"    : s.step_index,
            "tool_name"     : s.tool_name,
            "tool_input"    : s.tool_input,
            "tool_output"   : s.tool_output,
            "success"       : s.success,
            "error_message" : s.error_message,
            "error_category": s.error_category,
            "is_recoverable": s.is_recoverable,
            "reasoning"     : s.reasoning,
            "latency_ms"    : s.latency_ms,
            "created_at"    : datetime.now(timezone.utc).isoformat(),
        }
        for s in body
    ]

    try:
        db.table("episode_steps").insert(records).execute()
    except Exception as e:
        log.error(f"batch step insert failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "inserted": len(records)}


@app.post("/webhooks", status_code=201)
def create_webhook(
    body   : WebhookCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Register a webhook URL to be notified on low scores.
    URL is validated against SSRF blocklist at registration time.
    """
    # Validate URL for SSRF safety before storing
    _validate_webhook_url(body.url)

    db = get_db()
    try:
        db.table("webhooks").insert({
            "user_id"  : user_id,
            "url"      : body.url,
            "threshold": body.threshold,
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "url": body.url}


@app.get("/webhooks/deliveries")
def list_webhook_deliveries(
    limit  : int = Query(50, ge=1, le=200, description="Max deliveries to return"),
    offset : int = Query(0, ge=0),
    user_id: str = Depends(verify_api_key),
):
    """
    List webhook delivery attempts for the authenticated user.
    Shows delivery status, attempt count, and errors for debugging.
    Scoped to the user's own webhooks only.
    """
    db = get_db()

    # Get user's webhook IDs first
    hooks_resp = (
        db.table("webhooks")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    if not hooks_resp.data:
        return {"deliveries": [], "count": 0}

    hook_ids = [h["id"] for h in hooks_resp.data]

    # Fetch deliveries for those webhooks
    deliveries_resp = (
        db.table("webhook_deliveries")
        .select("id, webhook_id, episode_id, status, attempts, last_error, created_at")
        .in_("webhook_id", hook_ids)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "deliveries": deliveries_resp.data or [],
        "count": len(deliveries_resp.data or []),
    }


@app.post("/jobs", status_code=201)
def create_job(
    body   : JobCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Push a job to the episode_jobs queue.
    Called by the SDK once the agent run finishes.
    The merger worker polls this table and does the merge + scoring.
    """
    db = get_db()
    _assert_episode_owned(db, body.episode_id, user_id)

    # Update run_id on the episode row now that we have it. We also derive a
    # provisional outcome + totals *synchronously* from the steps already
    # written, so an episode is never left outcome-less if the merger worker
    # isn't running. The worker later overwrites these with full scoring +
    # embedding + clustering (its update is idempotent, so this is safe).
    episode_update = {"run_id": body.run_id}
    try:
        from merger.merger import derive_outcome
        steps = (
            db.table("episode_steps")
            .select("tool_name, success, latency_ms")
            .eq("episode_id", body.episode_id)
            .execute()
        ).data or []
        episode_update["outcome"] = derive_outcome(steps)
        episode_update["total_steps"] = len(steps)
        episode_update["total_latency_ms"] = sum(s.get("latency_ms") or 0 for s in steps)
    except Exception as exc:
        # Never block job creation on the provisional derive — worker will fill it.
        log.warning(f"provisional outcome derive failed for {body.episode_id}: {exc}")

    db.table("episodes").update(episode_update).eq("episode_id", body.episode_id).execute()

    try:
        db.table("episode_jobs").insert({
            "episode_id" : body.episode_id,
            "run_id"     : body.run_id,
            "agent_id"   : body.agent_id,
            "user_id"    : user_id,
            "task"       : body.task,
            "status"     : "pending",
            "retry_count": 0,
            "created_at" : datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return {"episode_id": body.episode_id, "queued": False, "reason": "already queued"}
        raise HTTPException(status_code=500, detail=str(e))

    return {"episode_id": body.episode_id, "queued": True}


# ---------------------------------------------------------------------------
# Endpoints — query
# ---------------------------------------------------------------------------
@app.get("/clusters")
def list_clusters(
    agent_id: str | None = Query(None, description="Filter by agent_id"),
    user_id : str        = Depends(verify_api_key),
):
    """
    List task clusters for the authenticated user.
    Optionally filter by agent_id.
    """
    db = get_db()
    query = db.table("episode_clusters").select("*").eq("user_id", user_id)
    if agent_id:
        query = query.eq("agent_id", agent_id)

    resp = query.order("episode_count", desc=True).execute()
    return {"clusters": resp.data or [], "count": len(resp.data or [])}

@app.get("/drift")
def get_drift(
    agent_id: str | None = Query(None, description="Filter by agent_id"),
    threshold: float     = Query(0.1, description="Minimum drop in score to consider as drift"),
    user_id : str        = Depends(verify_api_key),
):
    """
    Return clusters that have regressed in score by at least the threshold.
    """
    db = get_db()
    query = db.table("episode_clusters").select("*").eq("user_id", user_id).lt("drift", -abs(threshold))
    if agent_id:
        query = query.eq("agent_id", agent_id)

    resp = query.order("drift", desc=False).execute()
    return {"drifting_clusters": resp.data or [], "count": len(resp.data or [])}

@app.get("/drift/alerts")
def get_drift_alerts(
    limit  : int = Query(50, ge=1, le=200),
    user_id: str = Depends(verify_api_key),
):
    """
    Online drift alerts (§2.6): clusters whose recent score dropped below their
    baseline by > k·σ, detected by the worker's drift sweep. Joins through the
    user's clusters so only the caller's alerts are returned.
    """
    db = get_db()
    # Scope to this user's clusters.
    clusters = (
        db.table("episode_clusters").select("id, label, agent_id").eq("user_id", user_id).execute()
    ).data or []
    by_id = {c["id"]: c for c in clusters}
    if not by_id:
        return {"alerts": [], "count": 0}

    try:
        resp = (
            db.table("drift_alerts")
            .select("*")
            .in_("cluster_id", list(by_id.keys()))
            .order("detected_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        if "PGRST205" in str(exc):
            return {"alerts": [], "count": 0}
        raise

    alerts = []
    for a in resp.data or []:
        c = by_id.get(a["cluster_id"], {})
        alerts.append({**a, "cluster_label": c.get("label"), "agent_id": c.get("agent_id")})
    return {"alerts": alerts, "count": len(alerts)}

@app.get("/clusters/{cluster_id}/failures")
def get_cluster_failures(
    cluster_id: str,
    user_id   : str = Depends(verify_api_key),
):
    """
    Aggregate failing steps for a given cluster.
    """
    db = get_db()

    # First verify ownership
    c_resp = db.table("episode_clusters").select("id").eq("id", cluster_id).eq("user_id", user_id).execute()
    if not c_resp.data:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Get failed episodes in this cluster
    ep_resp = db.table("episodes").select("episode_id").eq("cluster_id", cluster_id).eq("outcome", "failure").execute()
    if not ep_resp.data:
        return {"failures": []}

    ep_ids = [r["episode_id"] for r in ep_resp.data]

    # Get failed steps for those episodes
    steps_resp = db.table("episode_steps").select("step_index, tool_name, error_category").in_("episode_id", ep_ids).eq("success", False).execute()

    # Group by tool_name and step_index
    from collections import Counter
    summary = Counter((s["step_index"], s["tool_name"], s["error_category"]) for s in (steps_resp.data or []))

    result = [
        {"step_index": k[0], "tool_name": k[1], "error_category": k[2], "count": v}
        for k, v in summary.most_common()
    ]

    return {"failures": result}

@app.get("/agents")
def list_agents(user_id: str = Depends(verify_api_key)):
    """List all distinct agent_ids that have ever run an episode for this user."""
    db = get_db()
    resp = (
        db.table("episodes")
        .select("agent_id")
        .eq("user_id", user_id)
        .execute()
    )
    agents = sorted({row["agent_id"] for row in (resp.data or []) if row.get("agent_id")})
    return {"agents": agents, "count": len(agents)}


@app.get("/agents/{agent_id}/regression")
def agent_regression(
    agent_id: str,
    from_ts : str | None = Query(None, alias="from", description="Baseline window start (ISO 8601). Default: 14 days ago."),
    to_ts   : str | None = Query(None, alias="to",   description="Boundary between baseline and 'after' (ISO 8601). Default: 7 days ago."),
    user_id : str        = Depends(verify_api_key),
):
    """
    Trajectory regression detection for an agent (§2.1).

    Compares the agent's recent episodes (>= `to`) against an earlier baseline
    ([`from`, `to`)) and surfaces per-scorer score deltas, step/outcome drift,
    newly-appearing failure signatures, and new trajectory shapes. Defaults to
    last-7-days vs prior-7-days when the window params are omitted.
    """
    from api.regression import fetch_and_compute
    db = get_db()
    return fetch_and_compute(db, user_id, agent_id, from_ts, to_ts)


@app.get("/compare")
def pairwise_compare(
    a       : str        = Query(..., description="Episode A id"),
    b       : str        = Query(..., description="Episode B id"),
    llm     : bool       = Query(True, description="Include the optional LLM pairwise verdict"),
    user_id : str        = Depends(verify_api_key),
):
    """
    Pairwise A/B comparison of two episodes (§2.4).

    Returns a deterministic trajectory diff (tool-sequence alignment, step/score
    deltas) plus, when `llm=true` and an LLM key is configured, a pairwise judge
    verdict on which run is better.
    """
    from eval.pairwise import compare_episodes
    db = get_db()
    try:
        return compare_episodes(db, user_id, a, b, use_llm=llm)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/episodes/{episode_id}/score/reference")
def score_reference(
    episode_id: str,
    body      : dict | None = None,
    user_id   : str         = Depends(verify_api_key),
):
    """
    On-demand reference-grounded scoring (§2.5): answer-relevance (+ faithfulness
    when `context` is provided). Opt-in to bound LLM spend.
    """
    from eval.reference import score_reference_metrics
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)
    context = (body or {}).get("context") if isinstance(body, dict) else None
    result = score_reference_metrics(db, episode_id, context=context)
    if result is None:
        raise HTTPException(status_code=422, detail="Episode has no final output to ground reference metrics on")
    return result


@app.post("/evaluate")
def evaluate_live(
    body    : EvaluateRequest,
    user_id : str = Depends(verify_api_key),
):
    """
    Live, in-the-loop verdict for a single step (LIVE_EVAL_WEDGE_PLAN §1).

    Called BEFORE a tool runs. Scores the proposed step against the agent's
    evaluation memory (failure signatures, cluster baselines, golden path) and
    returns an actionable verdict:

        {"action": "allow|warn|block|escalate", "score", "confidence",
         "reasons": [...], "suggest": {...}}

    Hot path is deterministic / vector-only (no LLM) to stay in the agent loop.
    Phase A is shadow-first: the engine *advises* (never blocks on its own); the
    verdict is logged to `live_verdicts` when that table exists. Fails open
    (`allow`) on any error so an AGeval hiccup never breaks the agent.
    """
    import time

    from eval.live import evaluate_step as _live_eval
    from eval.live import load_snapshot

    t0 = time.perf_counter()
    db = get_db()

    try:
        snap = load_snapshot(db, user_id, body.agent_id)

        # Embed the step's intent (tool + input + reasoning) for failure-sig
        # matching. Skipped silently if no embedding backend is configured —
        # the other two layers still run.
        embedding = None
        if snap.signatures:
            intent = " ".join(filter(None, [
                body.tool_name,
                str(body.tool_input) if body.tool_input is not None else None,
                body.reasoning,
            ]))
            embedding = _generate_embedding(intent)

        verdict = _live_eval(
            snap,
            tool_name=body.tool_name,
            tool_input=body.tool_input,
            step_embedding=embedding,
            tools_so_far=body.tools_so_far,
        )
        # Apply the agent's live policy (LIVE_EVAL_WEDGE_PLAN §2): turns the
        # advisory action into the enforced one. Only an enforce-mode policy can
        # promote escalate→block; absent a policy the advisory action stands.
        from eval.policy import apply_policy
        verdict = apply_policy(db, user_id, body.agent_id, verdict)
    except Exception as exc:
        # Fail open: an evaluator error must never block the caller's agent.
        log.warning(f"/evaluate failed open for agent={body.agent_id}: {exc}")
        from eval.live import Verdict
        verdict = Verdict(action="allow", score=1.0, confidence=0.0)

    verdict.latency_ms = int((time.perf_counter() - t0) * 1000)

    # Shadow-mode audit: record every verdict (best-effort) so the dashboard can
    # show "would-have-blocked" diffs and ROI. Never fails the request.
    _log_live_verdict(db, user_id, body, verdict)

    return verdict.to_dict()


class EvaluateStreamRequest(BaseModel):
    """Replay a proposed step sequence and stream a live verdict per step.

    Powers the dashboard's "Run live" view (watch the eval think): the client
    sends an agent_id and the ordered steps a workflow is about to take; the
    server loads the agent's memory snapshot ONCE and emits one SSE event per
    step, each carrying the real verdict from the live engine (failure-signature
    / baseline / golden-path layers). This is the real verdict engine evaluating
    a trajectory live — the same code path as POST /evaluate, streamed.
    """
    agent_id: str
    steps: list[dict]   # [{tool_name, tool_input?, reasoning?}, ...]

    @field_validator('agent_id')
    @classmethod
    def _check_agent(cls, v: str) -> str:
        return _validate_id(v, 'agent_id')


@app.post("/evaluate/stream")
def evaluate_stream(
    body    : EvaluateStreamRequest,
    user_id : str = Depends(verify_api_key),
):
    """Stream per-step live verdicts (Server-Sent Events) for a proposed run."""
    from fastapi.responses import StreamingResponse

    from eval.live import evaluate_step as _live_eval
    from eval.live import load_snapshot

    db = get_db()
    steps = body.steps[:50]   # bound the work

    def _gen():
        import time as _t

        try:
            snap = load_snapshot(db, user_id, body.agent_id)
        except Exception as exc:  # fail open — emit a cold snapshot notice
            snap = None
            yield _sse({"event": "warning", "message": f"snapshot load failed: {exc}"})

        # A one-line memory summary so the UI can show whether verdicts have teeth.
        mem = {
            "signatures": len(snap.signatures) if snap else 0,
            "has_golden": bool(snap and snap.golden),
            "numeric_baselines": len(snap.numeric_baselines) if snap else 0,
        }
        yield _sse({"event": "start", "agent_id": body.agent_id, "memory": mem,
                    "total_steps": len(steps)})

        tools_so_far: list[str] = []
        for i, st in enumerate(steps):
            tool = st.get("tool_name") or st.get("tool") or "step"
            tool_input = st.get("tool_input")
            reasoning = st.get("reasoning")
            tools_so_far.append(tool)

            t0 = _t.perf_counter()
            try:
                embedding = None
                if snap and snap.signatures:
                    intent = " ".join(filter(None, [tool, str(tool_input) if tool_input else None, reasoning]))
                    embedding = _generate_embedding(intent)
                verdict = _live_eval(snap, tool_name=tool, tool_input=tool_input,
                                     step_embedding=embedding, tools_so_far=list(tools_so_far)) \
                    if snap else None
                payload = verdict.to_dict() if verdict else {"action": "allow", "score": 1.0, "confidence": 0.0, "reasons": []}
            except Exception as exc:
                payload = {"action": "allow", "score": 1.0, "confidence": 0.0,
                           "reasons": [{"layer": "error", "message": str(exc)}]}
            payload.update({"event": "verdict", "step_index": i, "tool_name": tool,
                            "reasoning": reasoning,
                            "latency_ms": int((_t.perf_counter() - t0) * 1000)})
            yield _sse(payload)

        yield _sse({"event": "done", "steps": len(steps)})

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> str:
    import json as _json
    return f"data: {_json.dumps(obj)}\n\n"


def _log_live_verdict(db, user_id: str, body: "EvaluateRequest", verdict) -> None:
    """Best-effort insert into live_verdicts (skips silently if table absent)."""
    try:
        db.table("live_verdicts").insert({
            "user_id"          : user_id,
            "agent_id"         : body.agent_id,
            "episode_id"       : body.episode_id,
            "step_index"       : body.step_index,
            "input_hash"       : hashlib.sha256(
                f"{body.tool_name}|{body.tool_input}".encode()
            ).hexdigest()[:32],
            "action"           : verdict.action,
            "score"            : verdict.score,
            "confidence"       : verdict.confidence,
            "reasons"          : verdict.to_dict()["reasons"],
            "matched_signature": verdict.matched_signature_id,
            "latency_ms"       : verdict.latency_ms,
        }).execute()
    except Exception as exc:
        if "PGRST205" not in str(exc):  # table missing on un-migrated DB → fine
            log.debug(f"live_verdicts log skipped: {exc}")


@app.get("/agents/{agent_id}/policies")
def get_agent_policy(
    agent_id: str,
    user_id : str = Depends(verify_api_key),
):
    """
    The agent's live policy — its highest version, or a safe empty default
    (LIVE_EVAL_WEDGE_PLAN §2). Absent a policy, verdicts use their advisory
    action; the engine never blocks on its own.
    """
    db = get_db()
    try:
        resp = (
            db.table("live_policies")
            .select("version, mode, rules, created_at")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if "PGRST205" in str(exc):
            raise HTTPException(status_code=503, detail="live_policies table missing — run sdk/schema.sql")
        raise HTTPException(status_code=500, detail=str(exc))
    if not resp.data:
        return {"agent_id": agent_id, "mode": "log_only", "rules": [], "version": 0}
    row = resp.data[0]
    return {"agent_id": agent_id, **row}


class PolicyUpsert(BaseModel):
    """A new live policy version (LIVE_EVAL_WEDGE_PLAN §2)."""
    mode : str        = "log_only"   # log_only | enforce
    rules: list[dict] = []

    @field_validator('mode')
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ("log_only", "enforce"):
            raise ValueError("mode must be 'log_only' or 'enforce'")
        return v


@app.post("/agents/{agent_id}/policies", status_code=201)
def create_agent_policy(
    agent_id: str,
    body    : PolicyUpsert,
    user_id : str = Depends(verify_api_key),
):
    """
    Create a new policy version for an agent (LIVE_EVAL_WEDGE_PLAN §2).

    Versions are append-only and monotonically increasing; the highest version
    is the active one. Ship policies in `log_only` first (the default) — the
    dashboard shows "would-have-blocked" diffs — then re-POST with
    `mode: "enforce"` once you trust it. Zero-risk adoption path.
    """
    _validate_id(agent_id, "agent_id")
    db = get_db()
    try:
        prev = (
            db.table("live_policies")
            .select("version")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        next_version = ((prev.data or [{}])[0].get("version") or 0) + 1
        db.table("live_policies").insert({
            "user_id" : user_id,
            "agent_id": agent_id,
            "version" : next_version,
            "mode"    : body.mode,
            "rules"   : body.rules,
        }).execute()
    except Exception as exc:
        if "PGRST205" in str(exc):
            raise HTTPException(status_code=503, detail="live_policies table missing — run sdk/schema.sql")
        raise HTTPException(status_code=500, detail=str(exc))
    return {"agent_id": agent_id, "version": next_version, "mode": body.mode, "rules": body.rules}


@app.get("/agents/{agent_id}/live/verdicts")
def list_live_verdicts(
    agent_id: str,
    limit   : int = Query(100, ge=1, le=500),
    user_id : str = Depends(verify_api_key),
):
    """
    Recent live verdicts for an agent — the shadow-mode audit trail
    (LIVE_EVAL_WEDGE_PLAN §5.3). Powers the "would-have-blocked N runs" diff and
    the ROI tile. Returns a summary plus the recent rows.
    """
    db = get_db()
    try:
        resp = (
            db.table("live_verdicts")
            .select("step_index, action, score, confidence, reasons, latency_ms, episode_id, created_at")
            .eq("user_id", user_id)
            .eq("agent_id", agent_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        if "PGRST205" in str(exc):
            raise HTTPException(status_code=503, detail="live_verdicts table missing — run sdk/schema.sql")
        raise HTTPException(status_code=500, detail=str(exc))
    rows = resp.data or []
    summary = {a: 0 for a in ("allow", "warn", "escalate", "block")}
    for r in rows:
        summary[r.get("action", "allow")] = summary.get(r.get("action", "allow"), 0) + 1
    return {"agent_id": agent_id, "count": len(rows), "summary": summary, "verdicts": rows}


@app.get("/episodes")
def list_episodes(
    agent_id: str | None = Query(None, description="Filter by agent_id"),
    outcome : str | None = Query(None, description="Filter by outcome: success | partial | failure"),
    limit   : int        = Query(50,   ge=1, le=500),
    offset  : int        = Query(0,    ge=0),
    user_id : str        = Depends(verify_api_key),
):
    """
    List episodes for the authenticated user, newest first.
    Optionally filter by agent_id and/or outcome.
    """
    db    = get_db()
    query = (
        db.table("episodes")
        .select("episode_id, agent_id, run_id, task, outcome, total_steps, total_latency_ms, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if agent_id:
        query = query.eq("agent_id", agent_id)
    if outcome:
        query = query.eq("outcome", outcome)

    resp = query.execute()
    return {"episodes": resp.data or [], "count": len(resp.data or [])}


@app.get("/overview")
def dashboard_overview(
    limit  : int = Query(200, ge=1, le=1000, description="How many recent episodes to aggregate"),
    user_id: str = Depends(verify_api_key),
):
    """
    One-call dashboard KPI aggregate for the authenticated user.

    Aggregates the most recent `limit` episodes: outcome counts, average steps,
    average score per scorer, and the average breakdown of the custom-metric
    scorer (so the dashboard can show WHICH dimensions are weak, not just the
    composite). Everything here is computed from data the merger actually
    persists — no mock values.
    """
    db = get_db()

    eps_resp = (
        db.table("episodes")
        .select("episode_id, agent_id, outcome, total_steps, total_latency_ms, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    episodes = eps_resp.data or []
    total = len(episodes)

    if total == 0:
        return {
            "total_episodes": 0, "success_rate": 0.0, "failure_rate": 0.0,
            "partial_rate": 0.0, "avg_steps": 0.0, "avg_latency_ms": 0.0,
            "agent_count": 0, "scores": {}, "metric_breakdown": {},
        }

    successes = sum(1 for e in episodes if e.get("outcome") == "success")
    failures  = sum(1 for e in episodes if e.get("outcome") == "failure")
    partials  = sum(1 for e in episodes if e.get("outcome") == "partial")
    avg_steps = sum(e.get("total_steps") or 0 for e in episodes) / total
    avg_lat   = sum(e.get("total_latency_ms") or 0 for e in episodes) / total
    agents    = {e["agent_id"] for e in episodes if e.get("agent_id")}

    ep_ids = [e["episode_id"] for e in episodes]
    scores_resp = (
        db.table("episode_scores")
        .select("episode_id, scorer, score, breakdown")
        .in_("episode_id", ep_ids)
        .execute()
    )
    score_rows = scores_resp.data or []

    # Average composite score per scorer.
    by_scorer: dict[str, list[float]] = {}
    custom_breakdowns: list[dict] = []
    for row in score_rows:
        scorer = row.get("scorer")
        try:
            by_scorer.setdefault(scorer, []).append(float(row["score"]))
        except (TypeError, ValueError, KeyError):
            pass
        if scorer == "custom" and isinstance(row.get("breakdown"), dict):
            custom_breakdowns.append(row["breakdown"])

    scores = {
        scorer: round(sum(vals) / len(vals), 4)
        for scorer, vals in by_scorer.items() if vals
    }

    # Average each custom metric across episodes (numeric values only).
    metric_breakdown: dict[str, float] = {}
    if custom_breakdowns:
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for bd in custom_breakdowns:
            for k, v in bd.items():
                if isinstance(v, (int, float)):
                    sums[k] = sums.get(k, 0.0) + float(v)
                    counts[k] = counts.get(k, 0) + 1
        metric_breakdown = {
            k: round(sums[k] / counts[k], 4) for k in sums if counts[k]
        }

    return {
        "total_episodes": total,
        "success_rate"  : round(successes / total, 4),
        "failure_rate"  : round(failures / total, 4),
        "partial_rate"  : round(partials / total, 4),
        "avg_steps"     : round(avg_steps, 2),
        "avg_latency_ms": round(avg_lat, 1),
        "agent_count"   : len(agents),
        "scores"        : scores,            # {"rules": 0.8, "custom": 0.79, "llm_judge": 0.72}
        "metric_breakdown": metric_breakdown,  # {"success_rate": 0.9, "backtrack_rate": 1.0, ...}
    }


@app.get("/metrics/catalogue")
def metric_catalogue(user_id: str = Depends(verify_api_key)):
    """Public catalogue of all registered deterministic metrics + descriptions."""
    from ageval.metrics import list_metrics
    return {"metrics": list_metrics(), "count": len(list_metrics())}


@app.get("/episodes/{episode_id}")
def get_episode(
    episode_id: str,
    user_id   : str = Depends(verify_api_key),
):
    """
    Get one episode with its steps and score.
    """
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    ep_resp = (
        db.table("episodes")
        .select("*")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not ep_resp.data:
        raise HTTPException(status_code=404, detail="Episode not found")

    steps_resp = (
        db.table("episode_steps")
        .select("*")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    )

    score_resp = (
        db.table("episode_scores")
        .select("scorer, score, breakdown, created_at")
        .eq("episode_id", episode_id)
        .execute()
    )

    # Peer-relative annotation (§2.3): where each score sits vs runs like it.
    # Empty when the episode is unclustered or its cluster lacks a baseline —
    # callers simply fall back to the absolute scores above.
    try:
        from eval.relative import relative_scores
        relative = relative_scores(db, episode_id)
    except Exception as exc:
        log.warning(f"relative scoring failed for {episode_id}: {exc}")
        relative = {}

    return JSONResponse(
        content={
            "episode": ep_resp.data[0],
            "steps"  : steps_resp.data or [],
            "scores" : score_resp.data or [],
            "relative_scores": relative,
        },
        headers={"Cache-Control": "private, max-age=15"},
    )


@app.get("/episodes/{episode_id}/steps")
def get_episode_steps(
    episode_id: str,
    limit     : int = Query(100, ge=1, le=500, description="Max steps to return"),
    offset    : int = Query(0,   ge=0,         description="Offset for pagination"),
    user_id   : str = Depends(verify_api_key),
):
    """Get steps for an episode, ordered by step_index. Supports pagination."""
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    resp = (
        db.table("episode_steps")
        .select("*")
        .eq("episode_id", episode_id)
        .order("step_index")
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"episode_id": episode_id, "steps": resp.data or [], "limit": limit, "offset": offset}


def _score_provenance(scores: list[dict]) -> list[dict]:
    """Rank each scorer's metrics by shortfall (1.0 - value) so the biggest
    score-draggers surface first. Pure function — unit-tested directly."""
    provenance = []
    for s in scores:
        breakdown = s.get("breakdown") or {}
        contribs = []
        for metric, val in breakdown.items():
            if isinstance(val, (int, float)):
                contribs.append({
                    "metric": metric,
                    "value": round(float(val), 4),
                    "shortfall": round(max(0.0, 1.0 - float(val)), 4),
                })
        contribs.sort(key=lambda c: c["shortfall"], reverse=True)
        provenance.append({
            "scorer": s.get("scorer"),
            "score": s.get("score"),
            "top_drivers": contribs[:5],
            "all_metrics": contribs,
        })
    return provenance


@app.get("/episodes/{episode_id}/explain")
def explain_episode(
    episode_id: str,
    user_id   : str = Depends(verify_api_key),
):
    """Score provenance — *why* this episode scored the way it did.

    Transparency endpoint (Phase 2B): for each scorer it ranks the metrics by
    how much they moved the score, attaches the steps as evidence (tools used,
    failures + their classification), and replays the live in-the-loop verdicts
    that were rendered DURING the run (from `live_verdicts`). Everything here is
    derived from data already recorded — no re-scoring.
    """
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    ep_resp = (
        db.table("episodes").select("*").eq("episode_id", episode_id).limit(1).execute()
    )
    if not ep_resp.data:
        raise HTTPException(status_code=404, detail="Episode not found")

    steps = (
        db.table("episode_steps")
        .select("step_index, tool_name, success, error_category, is_recoverable, reasoning, latency_ms")
        .eq("episode_id", episode_id).order("step_index").execute()
    ).data or []

    scores = (
        db.table("episode_scores")
        .select("scorer, score, breakdown, created_at")
        .eq("episode_id", episode_id).execute()
    ).data or []

    # Rank each scorer's metrics by contribution (how far from a perfect 1.0).
    provenance = _score_provenance(scores)

    # Step evidence: which tools ran, which failed and why.
    failures = [
        {"step_index": st["step_index"], "tool": st["tool_name"],
         "error_category": st.get("error_category"), "recoverable": st.get("is_recoverable")}
        for st in steps if not st.get("success")
    ]
    tools_used = [st["tool_name"] for st in steps]

    # The live verdict trail rendered DURING the run (best-effort; table optional).
    verdict_trail = []
    try:
        vt = (
            db.table("live_verdicts")
            .select("step_index, action, score, confidence, reasons, matched_signature")
            .eq("episode_id", episode_id).order("step_index").execute()
        ).data or []
        verdict_trail = vt
    except Exception as exc:  # un-migrated DB / missing table
        if "PGRST205" not in str(exc):
            log.debug(f"explain: live_verdicts read skipped: {exc}")

    # Plain-English headline.
    if scores:
        worst = min(scores, key=lambda x: x.get("score") or 1.0)
        wb = worst.get("breakdown") or {}
        weak = sorted(((k, v) for k, v in wb.items() if isinstance(v, (int, float))),
                      key=lambda kv: kv[1])[:2]
        weak_str = ", ".join(f"{k}={v:.2f}" for k, v in weak) or "no weak metrics"
        summary = (f"{len(scores)} scorer(s); lowest is {worst.get('scorer')} at "
                   f"{worst.get('score')}. Weakest metrics: {weak_str}. "
                   f"{len(failures)} failed step(s) of {len(steps)}.")
    else:
        summary = (f"No scores yet (merge job may be pending). {len(steps)} steps recorded, "
                   f"{len(failures)} failed.")

    return JSONResponse(
        content={
            "episode_id": episode_id,
            "agent_id": ep_resp.data[0].get("agent_id"),
            "task": ep_resp.data[0].get("task"),
            "summary": summary,
            "score_provenance": provenance,
            "tools_used": tools_used,
            "failures": failures,
            "live_verdict_trail": verdict_trail,
            "step_count": len(steps),
        },
        headers={"Cache-Control": "private, max-age=15"},
    )


@app.get("/jobs/{episode_id}/status")
def get_job_status(
    episode_id: str,
    user_id   : str = Depends(verify_api_key),
):
    """
    Poll the merge job status for an episode.
    Returns status: pending | processing | done | failed
    """
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    resp = (
        db.table("episode_jobs")
        .select("status, retry_count, error_message, created_at, updated_at")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"No job found for episode {episode_id}")

    return {"episode_id": episode_id, **resp.data[0]}


@app.get("/recall")
def recall_episodes_api(
    task   : str = Query(..., description="Task string to embed and search"),
    k      : int = Query(3, ge=1, le=50, description="Number of episodes to return"),
    outcome: str | None = Query(None, description="Outcome filter e.g. success"),
    user_id: str = Depends(verify_api_key),
):
    """Find the k most relevant past episodes for a given task."""
    db = get_db()
    embedding = _generate_embedding(task)
    if not embedding:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured, cannot generate embeddings for task.",
        )

    try:
        result = db.rpc("match_episodes", {
            "query_embedding": embedding,
            "match_count"    : k * 3,  # overfetch if we need to filter outcome
            "filter_user_id" : user_id,
        }).execute()
        rows = result.data or []

        if outcome:
            rows = [r for r in rows if r.get("outcome") == outcome]

        rows = rows[:k]

        return {"episodes": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recall search failed: {e}")


@app.get("/similar")
def find_similar(
    episode_id: str = Query(..., description="Source episode to compare against"),
    k         : int = Query(5, ge=1, le=50, description="Number of similar episodes to return"),
    user_id   : str = Depends(verify_api_key),
):
    """
    Find the k most similar episodes using pgvector cosine similarity.
    Returns episodes ranked by embedding similarity to the source episode.
    Only returns episodes belonging to the authenticated user.

    Note: requires episode_embeddings rows to exist (populated by merger worker).
    """
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    # Fetch source embedding
    emb_resp = (
        db.table("episode_embeddings")
        .select("embedding")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not emb_resp.data:
        raise HTTPException(
            status_code=404,
            detail=f"No embedding found for episode {episode_id}. "
                   "Run the merger worker first to generate embeddings.",
        )

    source_embedding = emb_resp.data[0]["embedding"]

    # Use Supabase RPC to run pgvector similarity search
    # The function `match_episodes` must exist in your Supabase project:
    # See: sdk/schema.sql for the CREATE FUNCTION definition
    try:
        result = db.rpc("match_episodes", {
            "query_embedding": source_embedding,
            "match_count"    : k + 1,     # +1 because source itself will appear
            "filter_user_id" : user_id,
        }).execute()
        rows = result.data or []
        # Remove the source episode itself from results
        rows = [r for r in rows if r.get("episode_id") != episode_id][:k]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Similarity search failed: {e}")

    return {
        "source_episode_id": episode_id,
        "similar"          : rows,
    }


# ---------------------------------------------------------------------------
# Score trends — time-series data for dashboard charts
# ---------------------------------------------------------------------------
@app.get("/trends")
def score_trends(
    agent_id: str       = Query(..., description="Agent to get trends for"),
    scorer  : str       = Query("rules", description="Scorer name: 'rules' or 'llm_judge' or 'custom'"),
    limit   : int       = Query(50, ge=1, le=500, description="Max data points"),
    user_id : str       = Depends(verify_api_key),
):
    """
    Get score trends over time for a specific agent.
    Returns time-series data suitable for charting.
    """
    db = get_db()

    # Join episodes with scores to get time-series
    eps_resp = (
        db.table("episodes")
        .select("episode_id, agent_id, task, outcome, total_steps, created_at")
        .eq("user_id", user_id)
        .eq("agent_id", agent_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )

    if not eps_resp.data:
        return {"agent_id": agent_id, "scorer": scorer, "data_points": [], "count": 0}

    ep_ids = [e["episode_id"] for e in eps_resp.data]

    scores_resp = (
        db.table("episode_scores")
        .select("episode_id, score, breakdown, created_at")
        .eq("scorer", scorer)
        .in_("episode_id", ep_ids)
        .execute()
    )

    score_map = {s["episode_id"]: s for s in (scores_resp.data or [])}

    data_points = []
    for ep in eps_resp.data:
        score_data = score_map.get(ep["episode_id"])
        data_points.append({
            "episode_id" : ep["episode_id"],
            "agent_id"   : ep["agent_id"],
            "task"       : ep.get("task"),
            "outcome"    : ep.get("outcome"),
            "total_steps": ep.get("total_steps"),
            "score"      : float(score_data["score"]) if score_data else None,
            "breakdown"  : score_data.get("breakdown") if score_data else None,
            "timestamp"  : ep["created_at"],
        })

    return {
        "agent_id"    : agent_id,
        "scorer"      : scorer,
        "data_points" : data_points,
        "count"       : len(data_points),
    }


# ---------------------------------------------------------------------------
# Key management endpoints
# ---------------------------------------------------------------------------
@app.get("/keys")
def list_keys(user_id: str = Depends(verify_api_key)):
    """
    List all active API keys for the authenticated user.
    Useful for knowing which keys exist before rotating or revoking.
    """
    db = get_db()
    resp = (
        db.table("api_keys")
        .select("id, label, is_active, expires_at, last_used_at, created_at")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    return {"keys": resp.data or []}


@app.post("/keys", status_code=201)
def create_key(
    body: RegisterRequest,
    user_id: str = Depends(verify_api_key),
):
    """
    Issue a new AGeval API key for the authenticated user.

    This is how a signed-in user gets a key for their own agents: the dashboard
    calls this with the user's session (Supabase JWT) and shows the returned
    raw key ONCE. The key is scoped to the same user_id, so episodes the agent
    records show up under the user's account. The raw key is never stored —
    only its hash — so it cannot be shown again.
    """
    import secrets

    db = get_db()
    raw_key = f"ageval-sk-{secrets.token_hex(24)}"
    key_hash = _hash_key(raw_key)

    try:
        db.table("api_keys").insert({
            "key_hash" : key_hash,
            "user_id"  : user_id,
            "label"    : body.label or "default",
            "is_active": True,
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create key: {e}")

    log.info(f"API key issued for user={user_id} label='{body.label}'")
    return {
        "api_key": raw_key,
        "user_id": user_id,
        "label": body.label or "default",
        "message": "Store this key now — it will not be shown again.",
    }


@app.post("/keys/rotate", status_code=201)
def rotate_key(
    body: RegisterRequest,
    authorization: str = Header(...),
    user_id: str = Depends(verify_api_key),
):
    """
    Atomically rotate the caller's API key.
    - Issues a new key first (so the user always has ≥1 valid key).
    - Then deactivates the old key.
    - Returns the new key (shown once — store it immediately).

    The old key stops working after this call returns.
    """
    import secrets

    raw_old  = authorization.removeprefix("Bearer ").strip()
    old_hash = _hash_key(raw_old)
    db       = get_db()

    # Issue the new key FIRST — user always has at least one working key
    new_raw  = f"ageval-sk-{secrets.token_hex(24)}"
    new_hash = _hash_key(new_raw)

    try:
        db.table("api_keys").insert({
            "key_hash"  : new_hash,
            "user_id"   : user_id,
            "label"     : body.label or "rotated",
            "is_active" : True,
        }).execute()
    except Exception as e:
        # New key insert failed — old key is still active, no harm done
        raise HTTPException(status_code=500, detail=f"Rotation failed: {e}")

    # Now deactivate the old key (new key is already active as fallback)
    try:
        db.table("api_keys").update({"is_active": False}).eq("key_hash", old_hash).execute()
    except Exception as e:
        # Non-fatal: old key stays active alongside new key (user has 2 keys)
        log.warning(f"Old key deactivation failed during rotation for user={user_id}: {e}")

    log.info(f"API key rotated for user={user_id} label='{body.label}'")
    return {
        "api_key" : new_raw,
        "user_id" : user_id,
        "message" : "Old key is now inactive. Store the new key — it will not be shown again.",
    }


@app.delete("/keys/{key_id}", status_code=200)
def revoke_key(
    key_id: str,
    user_id: str = Depends(verify_api_key),
):
    """
    Revoke (deactivate) a specific key by its UUID.
    You can only revoke keys belonging to your own user_id.
    Use GET /keys to discover key IDs.
    """
    db = get_db()

    # Verify the key belongs to the caller
    resp = (
        db.table("api_keys")
        .select("id, user_id, is_active")
        .eq("id", key_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"Key {key_id} not found")
    if resp.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to revoke this key")
    if not resp.data[0]["is_active"]:
        return {"key_id": key_id, "revoked": False, "reason": "already inactive"}

    db.table("api_keys").update({"is_active": False}).eq("id", key_id).execute()
    log.info(f"API key {key_id} revoked by user={user_id}")
    return {"key_id": key_id, "revoked": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _assert_episode_owned(db, episode_id: str, user_id: str) -> None:
    """
    Verify that episode_id belongs to user_id.
    Raises 403 if not. 404 if episode doesn't exist.
    This prevents one user from writing steps/jobs to another user's episodes.
    """
    resp = (
        db.table("episodes")
        .select("user_id")
        .eq("episode_id", episode_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
    if resp.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this episode")

from api.datasets import router as datasets_router
from api.failures import router as failures_router
from api.redteam import router as redteam_router
from api.synthetic import router as synthetic_router

app.include_router(synthetic_router)
app.include_router(redteam_router)
app.include_router(datasets_router)
app.include_router(failures_router)
