"""
api/main.py

Thin ingestion API. This is the only server users talk to.
They never touch Supabase or LangSmith directly.

Endpoints:
    POST /steps   — write one episode_step row
    POST /jobs    — push one episode_job (triggers merger worker)
    POST /episodes — create a stub episode row (required before steps)

Auth:
    Every request must include header:  Authorization: Bearer ageval-sk-<key>
    The raw key is hashed (sha256) and looked up in api_keys table.
    If not found or inactive → 401.

Run locally:
    uvicorn api.main:app --reload

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

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="ageval ingestion API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


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

    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = _hash_key(raw_key)

    db = get_db()
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
    agent_id: str
    task: str | None = None


class StepCreate(BaseModel):
    episode_id: str
    step_index: int
    tool_name: str
    tool_input: dict | None = None
    tool_output: dict | None = None
    success: bool
    error_message: str | None = None
    error_category: str | None = None   # 'agent_error' | 'env_error' | 'unknown'
    is_recoverable: bool | None = None
    reasoning: str | None = None
    latency_ms: int | None = None


class JobCreate(BaseModel):
    episode_id: str
    run_id: str           # LangSmith run ID — pass "none" if not using LangSmith
    agent_id: str
    task: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/episodes", status_code=201)
def create_episode(
    body: EpisodeCreate,
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
            "agent_id": body.agent_id,
            "run_id": "pending",
            "task": body.task,
        }).execute()
    except Exception as e:
        # Duplicate episode_id — idempotent, not an error
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return {"episode_id": body.episode_id, "created": False}
        raise HTTPException(status_code=500, detail=str(e))

    return {"episode_id": body.episode_id, "created": True}


@app.post("/steps", status_code=201)
def create_step(
    body: StepCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Write one episode_step. Called by the SDK after every tool call.
    Fire-and-forget from the SDK side — response is not used.
    """
    db = get_db()
    record = {
        "episode_id": body.episode_id,
        "step_index": body.step_index,
        "tool_name": body.tool_name,
        "tool_input": body.tool_input,
        "tool_output": body.tool_output,
        "success": body.success,
        "error_message": body.error_message,
        "error_category": body.error_category,
        "is_recoverable": body.is_recoverable,
        "reasoning": body.reasoning,
        "latency_ms": body.latency_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        db.table("episode_steps").insert(record).execute()
    except Exception as e:
        log.error(f"step insert failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}


@app.post("/jobs", status_code=201)
def create_job(
    body: JobCreate,
    user_id: str = Depends(verify_api_key),
):
    """
    Push a job to the episode_jobs queue.
    Called by the SDK once the agent run finishes.
    The merger worker polls this table and does the merge + scoring.
    """
    db = get_db()

    # Update run_id on the episode row now that we have it
    db.table("episodes").update(
        {"run_id": body.run_id}
    ).eq("episode_id", body.episode_id).execute()

    try:
        db.table("episode_jobs").insert({
            "episode_id": body.episode_id,
            "run_id": body.run_id,
            "agent_id": body.agent_id,
            "task": body.task,
            "status": "pending",
            "retry_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return {"episode_id": body.episode_id, "queued": False, "reason": "already queued"}
        raise HTTPException(status_code=500, detail=str(e))

    return {"episode_id": body.episode_id, "queued": True}