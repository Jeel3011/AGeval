"""
worker.py

Distributed Celery worker for handling LLM-heavy, async tasks:
1. Red Teaming Attack Simulations
2. Synthetic Data Generation
3. Test Suite Evaluations
"""

import os
import time
import logging
from celery import Celery
import random

log = logging.getLogger(__name__)

# Configure Celery to use Redis (from docker-compose)
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("ageval_worker", broker=redis_url, backend=redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(bind=True, name="tasks.run_red_team_simulation")
def run_red_team_simulation(self, request_payload: dict, job_id: str):
    """
    Executes a barrage of adversarial prompts against a target agent.
    """
    log.info(f"Starting Red Team Simulation Job {job_id}")
    vectors = request_payload.get("attack_vectors", [])
    
    # Simulate multi-stage attack process
    for i, vector in enumerate(vectors):
        # Update progress in actual DB...
        progress = int(((i + 1) / len(vectors)) * 100)
        self.update_state(state='PROGRESS', meta={'progress': progress})
        
        # Fuzzing simulation
        time.sleep(2)
        log.info(f"[{job_id}] Testing vector: {vector}")

    log.info(f"Finished Red Team Simulation Job {job_id}")
    return {
        "status": "completed",
        "scorecard": {
            "overall_grade": "C-",
            "prompt_injection_bypass_rate": round(random.uniform(0.6, 0.9), 2),
            "dow_success_rate": round(random.uniform(0.1, 0.3), 2)
        }
    }


@celery_app.task(bind=True, name="tasks.generate_synthetic_data")
def generate_synthetic_data(self, request_payload: dict, job_id: str):
    """
    Uses LLMs to extrapolate seed examples into a large test dataset.
    """
    log.info(f"Starting Synthetic Generation Job {job_id}")
    num_to_gen = request_payload.get("num_examples_to_generate", 10)
    
    generated = []
    for i in range(num_to_gen):
        progress = int(((i + 1) / num_to_gen) * 100)
        self.update_state(state='PROGRESS', meta={'progress': progress})
        time.sleep(0.5)
        generated.append({
            "input": f"Synthetic input variation {i}",
            "expected_output": f"Expected output variation {i}"
        })
        
    log.info(f"Finished Synthetic Generation Job {job_id}")
    return {
        "status": "completed",
        "generated_count": len(generated),
        "data": generated
    }
