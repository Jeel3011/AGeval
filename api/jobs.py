from fastapi import APIRouter, HTTPException, Depends
import uuid
import logging
from typing import Dict, Any

from api.schemas import JobResponse, RedTeamRequest, SyntheticDataRequest
from api.deps import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/v1/jobs",
    tags=["Jobs"],
    dependencies=[Depends(verify_api_key)],
)

# Mock state for Async Job polling
# In production, this reads from the `jobs` table updated by Celery workers
_job_store: Dict[str, Dict[str, Any]] = {}

@router.get("/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str):
    """Poll for job status (queued, running, completed)."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Simulate progress for the UI polling
    if job["status"] == "running":
        job["progress"] += 20.0
        if job["progress"] >= 100.0:
            job["status"] = "completed"
            job["progress"] = 100.0
            if job["job_type"] == "red_team":
                job["result_summary"] = {
                    "overall_grade": "C-",
                    "prompt_injection_bypass_rate": 0.85,
                    "dow_success_rate": 0.15
                }
            elif job["job_type"] == "synthetic":
                job["result_summary"] = {
                    "generated_count": 50,
                    "dataset_id": "ds_new"
                }
    return job

@router.post("/redteam", response_model=JobResponse)
def enqueue_red_team_job(req: RedTeamRequest):
    """Enqueue a Red Teaming attack simulation into Celery/Redis."""
    job_id = f"job_rt_{uuid.uuid4().hex[:8]}"

    # TODO: Celery -> red_team_worker.delay(req.dict(), job_id)

    job_data = {
        "job_id": job_id,
        "project_id": req.project_id,
        "job_type": "red_team",
        "status": "running",
        "progress": 0.0
    }
    _job_store[job_id] = job_data
    log.info(f"Enqueued Red Team Job: {job_id}")
    return job_data

@router.post("/synthetic", response_model=JobResponse)
def enqueue_synthetic_job(req: SyntheticDataRequest):
    """Enqueue a Synthetic Data generation task into Celery/Redis."""
    job_id = f"job_syn_{uuid.uuid4().hex[:8]}"

    # TODO: Celery -> synthetic_data_worker.delay(req.dict(), job_id)

    job_data = {
        "job_id": job_id,
        "project_id": req.project_id,
        "job_type": "synthetic",
        "status": "running",
        "progress": 0.0
    }
    _job_store[job_id] = job_data
    log.info(f"Enqueued Synthetic Job: {job_id}")
    return job_data
