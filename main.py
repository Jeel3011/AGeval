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
import logging
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import time
from collections import defaultdict
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="ageval ingestion API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("AGEVAL_CORS_ORIGINS", "*").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate Limiting Middleware
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_REQUESTS = 100
_rate_limits = defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Simple in-memory rate limiting by IP
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Filter old requests
    active_requests = [req_time for req_time in _rate_limits[client_ip] if now - req_time < RATE_LIMIT_WINDOW]
    
    if active_requests:
        _rate_limits[client_ip] = active_requests
    elif client_ip in _rate_limits:
        del _rate_limits[client_ip]
        active_requests = []
    
    if len(active_requests) >= RATE_LIMIT_REQUESTS:
        return JSONResponse(status_code=429, content={"detail": "Too Many Requests"})
    
    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = []
    _rate_limits[client_ip].append(now)
    return await call_next(request)


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
    Returns user_id on success, raises 401 on failure.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    raw_key  = authorization.removeprefix("Bearer ").strip()
    key_hash = _hash_key(raw_key)

    db   = get_db()
    resp = db.table("api_keys") \
        .select("user_id") \
        .eq("key_hash", key_hash) \
        .eq("is_active", True) \
        .limit(1) \
        .execute()

    if not resp.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key")

    return resp.data[0]["user_id"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class EpisodeCreate(BaseModel):
    episode_id: str
    agent_id  : str
    task      : str | None = None


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
    tool_input     : dict | None = None
    tool_output    : dict | None = None
    success        : bool
    error_message  : str | None = None
    error_category : str | None = None   # 'agent_error' | 'env_error' | 'unknown'
    is_recoverable : bool | None = None
    reasoning      : str | None = None
    latency_ms     : int | None = None


class JobCreate(BaseModel):
    episode_id: str
    run_id    : str          # LangSmith run ID — pass "none" if not using LangSmith
    agent_id  : str
    task      : str | None = None


class RegisterRequest(BaseModel):
    label: str | None = "default"


class WebhookCreate(BaseModel):
    url      : str
    threshold: float = 0.7


# ---------------------------------------------------------------------------
# Endpoints — utility & onboarding
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


ADMIN_SECRET = os.environ.get("AGEVAL_ADMIN_SECRET", "dev-secret")

@app.post("/register", status_code=201)
def register(
    body: RegisterRequest,
    x_admin_secret: str = Header(None, description="Admin secret required for registration"),
):
    """Admin-only API key generation."""
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    db = get_db()
    import uuid
    # Generate a secure key
    raw_key = f"ageval-sk-{uuid.uuid4().hex}"
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
    """Register a webhook URL to be notified on low scores."""
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

    return {
        "episode": ep_resp.data[0],
        "steps"  : steps_resp.data or [],
        "scores" : score_resp.data or [],
    }


@app.get("/episodes/{episode_id}/steps")
def get_episode_steps(
    episode_id: str,
    user_id   : str = Depends(verify_api_key),
):
    """Get all steps for an episode, ordered by step_index."""
    db = get_db()
    _assert_episode_owned(db, episode_id, user_id)

    resp = (
        db.table("episode_steps")
        .select("*")
        .eq("episode_id", episode_id)
        .order("step_index")
        .execute()
    )
    return {"episode_id": episode_id, "steps": resp.data or []}


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