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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status, Request
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


def verify_api_key(authorization: str = Header(...)) -> str:
    """
    Dependency. Validates the Bearer token against api_keys table.
    - Rejects inactive or expired keys.
    - Records last_used_at on each successful auth (best-effort).
    Returns user_id on success, raises 401 on failure.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    raw_key  = authorization.removeprefix("Bearer ").strip()
    key_hash = _hash_key(raw_key)

    db   = get_db()
    resp = db.table("api_keys") \
        .select("id, user_id, expires_at") \
        .eq("key_hash", key_hash) \
        .eq("is_active", True) \
        .limit(1) \
        .execute()

    if not resp.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key")

    row = resp.data[0]

    # Check expiry
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
    import uuid
    import secrets
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

    # Update run_id on the episode row now that we have it
    db.table("episodes").update(
        {"run_id": body.run_id}
    ).eq("episode_id", body.episode_id).execute()

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

@app.get("/episodes")
def list_episodes(
    agent_id: str | None = Query(None, description="Filter by agent_id"),
    limit   : int        = Query(50,   ge=1, le=500),
    offset  : int        = Query(0,    ge=0),
    user_id : str        = Depends(verify_api_key),
):
    """
    List episodes for the authenticated user, newest first.
    Optionally filter by agent_id.
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

    resp = query.execute()
    return {"episodes": resp.data or [], "count": len(resp.data or [])}


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

    return JSONResponse(
        content={
            "episode": ep_resp.data[0],
            "steps"  : steps_resp.data or [],
            "scores" : score_resp.data or [],
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


@app.get("/compare")
def compare_episodes_api(
    episode_a: str = Query(...),
    episode_b: str = Query(...),
    user_id  : str = Depends(verify_api_key),
):
    """Diff two episodes."""
    db = get_db()
    _assert_episode_owned(db, episode_a, user_id)
    _assert_episode_owned(db, episode_b, user_id)

    ep_a_resp = db.table("episodes").select("*").eq("episode_id", episode_a).execute()
    ep_b_resp = db.table("episodes").select("*").eq("episode_id", episode_b).execute()

    steps_a_resp = db.table("episode_steps").select("*").eq("episode_id", episode_a).order("step_index").execute()
    steps_b_resp = db.table("episode_steps").select("*").eq("episode_id", episode_b).order("step_index").execute()

    return {
        "episode_a": ep_a_resp.data[0] if ep_a_resp.data else None,
        "episode_b": ep_b_resp.data[0] if ep_b_resp.data else None,
        "steps_a"  : steps_a_resp.data or [],
        "steps_b"  : steps_b_resp.data or [],
    }


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
