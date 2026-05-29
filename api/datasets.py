from fastapi import APIRouter, Depends
from typing import List
import uuid
import logging

from api.schemas import DatasetCreate, DatasetResponse
from api.deps import verify_api_key
# NOTE: still backed by an in-memory store (see _mock_datasets). Wire to the
# Supabase `golden_datasets`/`test_cases` tables before relying on this in prod.

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/v1/datasets",
    tags=["Datasets"],
    dependencies=[Depends(verify_api_key)],
)

# Mock DB for the transitional period before Supabase is fully seeded
_mock_datasets = [
    {
        "id": "ds_1",
        "project_id": "prj_9x8c7v6b",
        "name": "Customer Support Queries",
        "version": "v3",
        "test_case_count": 1250,
        "last_updated": "2 hours ago"
    },
    {
        "id": "ds_2",
        "project_id": "prj_9x8c7v6b",
        "name": "Adversarial Jailbreaks",
        "version": "v1",
        "test_case_count": 420,
        "last_updated": "Yesterday"
    }
]

@router.get("", response_model=List[DatasetResponse])
def get_datasets(project_id: str):
    """Fetch all golden datasets for a given project."""
    # TODO: Connect to Supabase `golden_datasets` table
    results = [d for d in _mock_datasets if d["project_id"] == project_id]
    return results

@router.post("", response_model=DatasetResponse)
def create_dataset(dataset: DatasetCreate):
    """Create a new golden dataset and insert its test cases."""
    # TODO: Insert into Supabase `golden_datasets` and `test_cases` tables
    new_id = f"ds_{uuid.uuid4().hex[:8]}"
    new_ds = {
        "id": new_id,
        "project_id": dataset.project_id,
        "name": dataset.name,
        "version": dataset.version,
        "test_case_count": len(dataset.test_cases),
        "last_updated": "Just now"
    }
    _mock_datasets.append(new_ds)
    log.info(f"Created dataset {new_id} with {len(dataset.test_cases)} cases.")
    return new_ds
