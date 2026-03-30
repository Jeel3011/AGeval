"""
merger/worker.py

Polling worker that picks jobs from episode_jobs and runs the merger.

Run it with:
    python -m merger.worker

It loops forever, polling every POLL_INTERVAL seconds.
No Redis, no ARQ — pure Supabase polling using SELECT FOR UPDATE SKIP LOCKED
via a raw SQL call. Simpler to debug, no extra infra dependency.

To run multiple workers in parallel just launch multiple processes —
SKIP LOCKED guarantees they never grab the same job.
"""

import os
import time
import logging
import signal
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
from merger.merger import run_merger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

POLL_INTERVAL  = 5    # seconds between polls when queue is empty
MAX_RETRIES    = 3
REQUEUE_DELAY  = 30   # seconds to wait before requeueing a not-ready trace


def get_client():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

def pick_job(client) -> dict | None:
    result = client.rpc("pick_next_job").execute()

    # RPC now returns a single JSON object or null
    if result.data is None:
        return None

    # result.data is already a dict
    if isinstance(result.data, dict):
        return result.data

    # safety: if it came back as a list for any reason, take first element
    if isinstance(result.data, list) and len(result.data) > 0:
        return result.data[0]

    return None

def requeue_job(client, job_id: str, current_retry: int, error: str | None = None):
    """Put a job back to pending after a transient failure."""
    client.table("episode_jobs").update({
        "status"       : "pending",
        "locked_at"    : None,
        "retry_count"  : current_retry + 1,
        "error_message": error,
    }).eq("id", job_id).execute()


def fail_job(client, job_id: str, error: str):
    """Mark a job permanently failed after MAX_RETRIES."""
    client.table("episode_jobs").update({
        "status"       : "failed",
        "error_message": error,
        "locked_at"    : None,
    }).eq("id", job_id).execute()


def done_job(client, job_id: str):
    client.table("episode_jobs").update({
        "status"   : "done",
        "locked_at": None,
    }).eq("id", job_id).execute()


def process_job(client, job: dict):
    job_id      = job["id"]
    episode_id  = job["episode_id"]
    run_id      = job["run_id"]
    agent_id    = job["agent_id"]
    task        = job.get("task")
    retry_count = job.get("retry_count", 0)

    log.info(f"Processing job {job_id} | episode {episode_id} | retry {retry_count}")

    try:
        result = run_merger(
            client     = client,
            episode_id = episode_id,
            run_id     = run_id,
            agent_id   = agent_id,
            task       = task,
        )

        if result == "not_ready":
            # LangSmith trace not ready yet — requeue with delay
            log.info(f"Trace not ready for {run_id}, requeueing in {REQUEUE_DELAY}s")
            time.sleep(REQUEUE_DELAY)
            requeue_job(client, job_id, retry_count, error="trace_not_ready")
            return

        done_job(client, job_id)
        log.info(f"Job {job_id} done — episode {episode_id} merged successfully")

    except Exception as exc:
        log.error(f"Job {job_id} failed: {exc}", exc_info=True)

        if retry_count + 1 >= MAX_RETRIES:
            fail_job(client, job_id, str(exc))
            log.error(f"Job {job_id} permanently failed after {MAX_RETRIES} retries")
        else:
            requeue_job(client, job_id, retry_count, error=str(exc))
            log.info(f"Job {job_id} requeued (attempt {retry_count + 1}/{MAX_RETRIES})")


def run():
    log.info("Episode merger worker starting")
    client = get_client()

    # Graceful shutdown on SIGINT / SIGTERM
    running = {"value": True}

    def _stop(sig, frame):
        log.info("Shutdown signal received, finishing current job...")
        running["value"] = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running["value"]:
        job = pick_job(client)

        if job is None:
            time.sleep(POLL_INTERVAL)
            continue

        process_job(client, job)

    log.info("Worker stopped cleanly")


if __name__ == "__main__":
    run()