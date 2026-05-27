from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime
import uuid

# ---------------------------------------------------------------------------
# Dataset Schemas
# ---------------------------------------------------------------------------

class TestCase(BaseModel):
    input_data: Dict[str, Any]
    expected_output: str
    context: Optional[List[str]] = None

class DatasetCreate(BaseModel):
    project_id: str
    name: str
    version: str = "v1"
    test_cases: List[TestCase]

class DatasetResponse(BaseModel):
    id: str
    project_id: str
    name: str
    version: str
    test_case_count: int
    last_updated: str

# ---------------------------------------------------------------------------
# Job & Task Schemas
# ---------------------------------------------------------------------------

class JobResponse(BaseModel):
    job_id: str
    project_id: str
    job_type: str  # 'red_team', 'synthetic', 'evaluation'
    status: str    # 'queued', 'running', 'completed', 'failed'
    progress: float
    result_summary: Optional[Dict[str, Any]] = None

class RedTeamRequest(BaseModel):
    project_id: str
    target_agent_url: Optional[str] = None
    attack_vectors: List[str] = ["prompt_injection", "data_exfiltration", "roleplay_jailbreak"]

class SyntheticDataRequest(BaseModel):
    project_id: str
    dataset_name: str
    seed_examples: List[Dict[str, Any]]
    num_examples_to_generate: int = 10

# ---------------------------------------------------------------------------
# Analytics Schemas
# ---------------------------------------------------------------------------

class KPIDashboardResponse(BaseModel):
    total_traces: int
    avg_faithfulness: float
    failure_rate: float
    avg_latency_ms: float
    traces_change_pct: float
    faithfulness_change_pct: float
    failure_change_pct: float
    latency_change_pct: float
