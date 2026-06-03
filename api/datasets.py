"""
api/datasets.py

Golden-dataset management, backed by Supabase (golden_datasets +
dataset_test_cases tables — see sdk/schema.sql).

Datasets are scoped per user: the authenticated user_id is taken from the API
key, so callers can only see and mutate their own datasets. RLS enforces the
same isolation at the Postgres layer.

If the dataset tables haven't been created yet (sdk/schema.sql not applied),
reads return an empty list and writes raise a clear 503 telling the operator to
run the migration — no silent in-memory data loss.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import DatasetCreate, DatasetResponse
from api.deps import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/v1/datasets",
    tags=["Datasets"],
    dependencies=[Depends(verify_api_key)],
)

_MISSING_TABLE = "PGRST205"  # PostgREST: relation not found in schema cache


def _db():
    # Lazy import keeps the module importable without a live Supabase (tests).
    from main import get_db
    return get_db()


def _is_missing_table(exc: Exception) -> bool:
    return _MISSING_TABLE in str(exc)


def _humanize(ts: str | None) -> str:
    """Render an ISO timestamp as a short relative label for the UI."""
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ts
    delta = datetime.now(timezone.utc) - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


@router.get("", response_model=List[DatasetResponse])
def get_datasets(project_id: str, user_id: str = Depends(verify_api_key)):
    """Fetch all golden datasets for a project owned by the authenticated user."""
    db = _db()
    try:
        ds_resp = (
            db.table("golden_datasets")
            .select("id, project_id, name, version, updated_at")
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        if _is_missing_table(exc):
            log.warning("golden_datasets table missing — run sdk/schema.sql")
            return []
        raise

    rows = ds_resp.data or []
    if not rows:
        return []

    # Count test cases per dataset in a single query.
    ids = [r["id"] for r in rows]
    counts: dict[str, int] = {i: 0 for i in ids}
    try:
        tc_resp = (
            db.table("dataset_test_cases")
            .select("dataset_id")
            .in_("dataset_id", ids)
            .execute()
        )
        for tc in tc_resp.data or []:
            counts[tc["dataset_id"]] = counts.get(tc["dataset_id"], 0) + 1
    except Exception as exc:
        if not _is_missing_table(exc):
            raise

    return [
        DatasetResponse(
            id=r["id"],
            project_id=r["project_id"],
            name=r["name"],
            version=r["version"],
            test_case_count=counts.get(r["id"], 0),
            last_updated=_humanize(r.get("updated_at")),
        )
        for r in rows
    ]


@router.post("", response_model=DatasetResponse)
def create_dataset(dataset: DatasetCreate, user_id: str = Depends(verify_api_key)):
    """Create a golden dataset and insert its test cases (atomic-ish: dataset
    first, then its cases). Persisted to Supabase, scoped to the caller."""
    db = _db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        ds_resp = (
            db.table("golden_datasets")
            .insert({
                "user_id": user_id,
                "project_id": dataset.project_id,
                "name": dataset.name,
                "version": dataset.version,
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

    cases = [
        {
            "dataset_id": new_id,
            "input_data": tc.input_data,
            "expected_output": tc.expected_output,
            "context": tc.context,
            "created_at": now,
        }
        for tc in dataset.test_cases
    ]
    if cases:
        try:
            db.table("dataset_test_cases").insert(cases).execute()
        except Exception as exc:
            # Roll back the dataset row so we don't leave an empty dataset behind.
            try:
                db.table("golden_datasets").delete().eq("id", new_id).execute()
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"Failed to insert test cases: {exc}",
            ) from exc

    log.info(f"Created dataset {new_id} ({len(cases)} cases) for user {user_id}")
    return DatasetResponse(
        id=new_id,
        project_id=dataset.project_id,
        name=dataset.name,
        version=dataset.version,
        test_case_count=len(cases),
        last_updated="just now",
    )
