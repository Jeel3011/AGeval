"""
api/failures.py

Failure-pattern memory API + the trace→eval loop (EVAL_DEPTH_AND_MEMORY_PLAN
§1.4 / §2.2).

Endpoints (all scoped to the authenticated user, like api/datasets.py):
  • GET  /v1/failures                      — list this user's failure signatures
                                             (optionally filtered by agent_id),
                                             ordered by recurrence.
  • GET  /v1/failures/{id}                 — one signature + its occurrence log
                                             (which episodes hit it, when).
  • POST /v1/failures/{id}/generate-eval   — the flagship "one click → golden
                                             test case": turn a signature into a
                                             golden-dataset entry so the failure
                                             can't silently return after a fix.

If the failure_memory tables haven't been created yet (sdk/schema.sql not
applied), reads return empty and the generate endpoint raises a clear 503 —
the same graceful pattern api/datasets.py uses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import verify_api_key
from api.schemas import DatasetResponse, FailureSignatureResponse, GenerateEvalRequest

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/v1/failures",
    tags=["Failures"],
    dependencies=[Depends(verify_api_key)],
)

_MISSING_TABLE = "PGRST205"


def _db():
    from main import get_db
    return get_db()


def _is_missing_table(exc: Exception) -> bool:
    return _MISSING_TABLE in str(exc)


@router.get("", response_model=List[FailureSignatureResponse])
def list_failures(
    agent_id: Optional[str] = Query(None, description="Filter by agent_id"),
    user_id: str = Depends(verify_api_key),
):
    """List failure signatures for the user, most-recurrent first."""
    db = _db()
    try:
        query = (
            db.table("failure_memory")
            .select("id, agent_id, signature, label, occurrences, first_seen, "
                    "last_seen, sample_episode_id, sample_error")
            .eq("user_id", user_id)
        )
        if agent_id:
            query = query.eq("agent_id", agent_id)
        resp = query.order("occurrences", desc=True).execute()
    except Exception as exc:
        if _is_missing_table(exc):
            log.warning("failure_memory table missing — run sdk/schema.sql")
            return []
        raise

    return [FailureSignatureResponse(**row) for row in (resp.data or [])]


@router.get("/{failure_id}")
def get_failure(failure_id: str, user_id: str = Depends(verify_api_key)):
    """One failure signature plus its occurrence log (recurrence lifecycle)."""
    db = _db()
    try:
        f_resp = (
            db.table("failure_memory")
            .select("*")
            .eq("id", failure_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if _is_missing_table(exc):
            raise HTTPException(status_code=404, detail="Failure not found") from exc
        raise

    if not f_resp.data:
        raise HTTPException(status_code=404, detail="Failure not found")

    signature = f_resp.data[0]

    occ_resp = (
        db.table("failure_occurrences")
        .select("episode_id, step_index, occurred_at")
        .eq("failure_id", failure_id)
        .order("occurred_at", desc=True)
        .execute()
    )

    # Don't leak the raw embedding centroid to API clients.
    signature.pop("centroid", None)
    return {"failure": signature, "occurrences": occ_resp.data or []}


@router.post("/{failure_id}/generate-eval", response_model=DatasetResponse)
def generate_eval(
    failure_id: str,
    body: GenerateEvalRequest,
    user_id: str = Depends(verify_api_key),
):
    """Turn a failure signature into a golden-dataset regression test case.

    Closes the trace→eval loop: the triggering task becomes the input, and the
    assertion is that the previously-failing step must now succeed. Re-running
    the agent against this dataset proves the failure stays fixed.
    """
    db = _db()

    # 1. Load the signature (and confirm ownership).
    try:
        f_resp = (
            db.table("failure_memory")
            .select("*")
            .eq("id", failure_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if _is_missing_table(exc):
            raise HTTPException(
                status_code=503,
                detail="Failure memory not initialized. Run sdk/schema.sql to create "
                       "the failure_memory / failure_occurrences tables.",
            ) from exc
        raise

    if not f_resp.data:
        raise HTTPException(status_code=404, detail="Failure not found")

    signature = f_resp.data[0]
    sample_episode_id = signature.get("sample_episode_id")

    # 2. Recover the triggering task from the sample episode.
    task = None
    if sample_episode_id:
        ep_resp = (
            db.table("episodes")
            .select("task")
            .eq("episode_id", sample_episode_id)
            .limit(1)
            .execute()
        )
        if ep_resp.data:
            task = ep_resp.data[0].get("task")

    failing_tool = (signature["signature"].split("|") + ["?"])[1]
    assertion = (
        f"The agent must complete the task without the '{failing_tool}' "
        f"{signature.get('label') or 'failure'} recurring."
    )

    now = datetime.now(timezone.utc).isoformat()
    name = body.dataset_name or f"regression: {signature.get('label') or signature['signature']}"

    # 3. Create the golden dataset + a single regression test case.
    try:
        ds_resp = (
            db.table("golden_datasets")
            .insert({
                "user_id": user_id,
                "project_id": body.project_id,
                "name": name,
                "version": "v1",
                "created_at": now,
                "updated_at": now,
            })
            .execute()
        )
    except Exception as exc:
        if _is_missing_table(exc):
            raise HTTPException(
                status_code=503,
                detail="Dataset storage not initialized. Run sdk/schema.sql to create "
                       "the golden_datasets / dataset_test_cases tables.",
            ) from exc
        raise

    if not ds_resp.data:
        raise HTTPException(status_code=500, detail="Failed to create dataset")

    new_id = ds_resp.data[0]["id"]

    test_case = {
        "dataset_id": new_id,
        "input_data": {
            "task": task or "(task unavailable — captured from production failure)",
            "from_failure_signature": signature["signature"],
            "from_episode": sample_episode_id,
        },
        "expected_output": assertion,
        "context": {"sample_error": signature.get("sample_error")},
        "created_at": now,
    }
    try:
        db.table("dataset_test_cases").insert(test_case).execute()
    except Exception as exc:
        try:
            db.table("golden_datasets").delete().eq("id", new_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to insert test case: {exc}") from exc

    log.info(
        f"Generated regression eval {new_id} from failure {failure_id} for user {user_id}"
    )
    return DatasetResponse(
        id=new_id,
        project_id=body.project_id,
        name=name,
        version="v1",
        test_case_count=1,
        last_updated="just now",
    )
