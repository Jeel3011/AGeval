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

Key fixes over v1:
  - No more time.sleep(backoff) blocking the entire worker thread.
    Not-ready jobs are immediately requeued with a scheduled_at timestamp.
    The poll query skips jobs where scheduled_at > now().
  - Dead-worker reclamation: jobs stuck in 'processing' for > 10 minutes are
    reclaimed back to 'pending' automatically.
  - Webhook delivery is recorded in webhook_deliveries table with retries,
    not fire-and-forget daemon threads.
  - LangSmith is fully optional (handled in merger.py).

Env vars required:
    AGEVAL_SUPABASE_URL
    AGEVAL_SUPABASE_SERVICE_KEY
    OPENAI_API_KEY              (optional — for embedding generation)
    LANGSMITH_API_KEY           (optional — only for LangChain agents)
"""

import os
import time
import logging
import signal
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
from merger.merger import run_merger
from eval.rules import score_episode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

POLL_INTERVAL        = 5    # seconds between polls when queue is empty
MAX_RETRIES          = 3
NOT_READY_BACKOFF    = 30   # seconds for first not-ready requeue (doubles each time)
STALE_JOB_MINUTES   = 10   # minutes before a processing job is considered dead
RECLAIM_EVERY_N     = 6    # reclaim stale jobs every N poll cycles (~30s)


def get_client():
    return create_client(
        os.environ["AGEVAL_SUPABASE_URL"],
        os.environ["AGEVAL_SUPABASE_SERVICE_KEY"],
    )


def pick_job(client) -> dict | None:
    result = client.rpc("pick_next_job").execute()

    if result.data is None:
        return None

    if isinstance(result.data, dict):
        return result.data

    if isinstance(result.data, list) and len(result.data) > 0:
        return result.data[0]

    return None


def requeue_job(client, job_id: str, current_retry: int, error: str | None = None, delay_seconds: int = 0):
    """
    Put a job back to pending after a transient failure.

    For not-ready traces: set scheduled_at = now() + delay_seconds so the
    worker doesn't immediately re-pick it (no more sleep blocking!).
    """
    scheduled_at = None
    if delay_seconds > 0:
        scheduled_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()

    update = {
        "status"       : "pending",
        "locked_at"    : None,
        "retry_count"  : current_retry + 1,
        "error_message": error,
    }
    if scheduled_at:
        update["scheduled_at"] = scheduled_at

    client.table("episode_jobs").update(update).eq("id", job_id).execute()


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


def reclaim_stale_jobs(client):
    """
    Find jobs stuck in 'processing' with locked_at older than STALE_JOB_MINUTES
    and reset them back to 'pending'. This handles dead/crashed workers.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_JOB_MINUTES)).isoformat()
    try:
        resp = client.rpc("reclaim_stale_jobs", {"cutoff_time": cutoff}).execute()
        count = len(resp.data) if resp.data else 0
        if count:
            log.warning(f"Reclaimed {count} stale job(s) stuck in 'processing'")
    except Exception as exc:
        # Non-fatal — the function might not exist yet if schema not updated
        log.debug(f"reclaim_stale_jobs RPC failed (schema may need updating): {exc}")


def _deliver_webhooks(client, episode_id: str, score_val: float):
    """
    Deliver webhooks for a scored episode with retry and audit trail.
    Writes to webhook_deliveries table (if it exists) for tracking.
    Falls back to best-effort delivery if table doesn't exist.

    SSRF protection: re-resolves DNS and validates against private IP ranges
    at delivery time (not just registration) to prevent DNS rebinding attacks.
    """
    import urllib.request
    import json
    import hmac
    import hashlib
    import socket
    import ipaddress

    # Private/internal IP ranges — SSRF blocklist
    _PRIVATE_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
    ]

    def _is_safe_url(url: str) -> bool:
        """Re-resolve DNS at delivery time and check against private IP ranges."""
        try:
            from urllib.parse import urlparse
            hostname = urlparse(url).hostname
            if not hostname:
                return False
            addr_str = socket.gethostbyname(hostname)
            addr = ipaddress.ip_address(addr_str)
            for network in _PRIVATE_RANGES:
                if addr in network:
                    log.warning(f"Webhook URL {url} resolves to private IP {addr_str} — blocked (SSRF)")
                    return False
            return True
        except Exception as exc:
            log.warning(f"Webhook URL DNS resolution failed for {url}: {exc} — blocked")
            return False

    try:
        ep_resp = client.table("episodes").select("user_id").eq("episode_id", episode_id).execute()
        if not ep_resp.data or not ep_resp.data[0].get("user_id"):
            return

        user_id = ep_resp.data[0]["user_id"]
        hooks_resp = (
            client.table("webhooks")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        if not hooks_resp.data:
            return

        payload_dict = {"episode_id": episode_id, "score": score_val, "event": "episode_scored"}
        payload_bytes = json.dumps(payload_dict).encode()

        webhook_secret = os.environ.get("AGEVAL_WEBHOOK_SECRET", "")

        for hook in hooks_resp.data:
            if score_val >= float(hook["threshold"]):
                continue  # score above threshold — no alert needed

            url = hook["url"]
            hook_id = hook.get("id", "unknown")

            # SSRF check: re-validate DNS at delivery time (prevents DNS rebinding)
            if not _is_safe_url(url):
                try:
                    client.table("webhook_deliveries").insert({
                        "webhook_id" : hook_id,
                        "episode_id" : episode_id,
                        "status"     : "failed",
                        "attempts"   : 0,
                        "last_error" : "SSRF blocked: URL resolves to private/internal IP at delivery time",
                        "created_at" : datetime.now(timezone.utc).isoformat(),
                    }).execute()
                except Exception:
                    pass
                continue

            # Build HMAC signature for receiver verification
            sig = hmac.new(
                webhook_secret.encode() if webhook_secret else b"unsigned",
                payload_bytes,
                hashlib.sha256,
            ).hexdigest()

            headers = {
                "Content-Type"       : "application/json",
                "X-AGeval-Signature" : f"sha256={sig}",
                "X-AGeval-Episode"   : episode_id,
            }

            delivered = False
            last_error = None

            for attempt in range(1, 4):  # 3 attempts
                try:
                    req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=5):
                        log.info(f"Webhook delivered to {url} for {episode_id} (attempt {attempt})")
                        delivered = True
                        break
                except Exception as exc:
                    last_error = str(exc)
                    log.warning(f"Webhook attempt {attempt}/3 to {url} failed: {exc}")
                    if attempt < 3:
                        time.sleep(2 ** attempt)  # 2s, 4s backoff between retries

            # Record delivery result in webhook_deliveries (best-effort)
            try:
                client.table("webhook_deliveries").insert({
                    "webhook_id" : hook_id,
                    "episode_id" : episode_id,
                    "status"     : "delivered" if delivered else "failed",
                    "attempts"   : 3 if not delivered else attempt,
                    "last_error" : last_error,
                    "created_at" : datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception:
                pass  # table may not exist yet — non-fatal

    except Exception as e:
        log.warning(f"Failed to deliver webhooks for {episode_id}: {e}")


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
            # Requeue with scheduled_at delay — no blocking sleep!
            backoff = NOT_READY_BACKOFF * (2 ** retry_count)  # 30s, 60s, 120s...
            log.info(f"Trace not ready for {run_id}, scheduling retry in {backoff}s (attempt {retry_count + 1})")
            requeue_job(client, job_id, retry_count, error="trace_not_ready", delay_seconds=backoff)
            return

        done_job(client, job_id)
        log.info(f"Job {job_id} done — episode {episode_id} merged successfully")

        # Score immediately after every successful merge
        try:
            score_result = score_episode(client, episode_id)
            score_val = float(score_result["score"])
            log.info(
                f"Scored {episode_id} | "
                f"score={score_val} | "
                f"breakdown={score_result['breakdown']}"
            )

            # LLM judge (optional — requires OPENAI_API_KEY)
            try:
                from eval.llm_judge import judge_episode
                judge_result = judge_episode(client, episode_id)
                log.info(f"LLM judge scored {episode_id} | score={judge_result['score']}")
            except Exception as judge_exc:
                log.warning(f"LLM judge failed for {episode_id}: {judge_exc}")

            # Webhook delivery with retry and audit
            _deliver_webhooks(client, episode_id, score_val)

        except Exception as score_exc:
            # Scoring failure never kills the worker or the job
            log.error(f"Scoring failed for {episode_id}: {score_exc}")

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

    poll_cycle = 0
    while running["value"]:
        poll_cycle += 1

        # Periodically reclaim stale jobs from dead workers
        if poll_cycle % RECLAIM_EVERY_N == 0:
            reclaim_stale_jobs(client)

        job = pick_job(client)

        if job is None:
            time.sleep(POLL_INTERVAL)
            continue

        process_job(client, job)

    log.info("Worker stopped cleanly")


if __name__ == "__main__":
    run()
