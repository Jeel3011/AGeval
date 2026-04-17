"""
rate_limiter.py

Pluggable rate limiter for the AGeval ingestion API.

Backends (tried in order):
  1. Redis  — shared across all workers/processes; keyed by user/API key.
             Requires REDIS_URL env var (e.g. redis://localhost:6379/0).
             Uses atomic INCR + EXPIRE pipeline — no race conditions.
  2. In-memory fallback — same logic as before, single-process only.
             Used automatically when REDIS_URL is not set or Redis is
             unreachable. Logs a one-time warning on first fallback.

Config (env vars):
  REDIS_URL              — Redis connection string (optional)
  RATE_LIMIT_REQUESTS    — max requests per window (default: 100)
  RATE_LIMIT_WINDOW      — window in seconds (default: 60)
  RATE_LIMIT_KEY_PREFIX  — Redis key namespace (default: ageval:rl:)
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

log = logging.getLogger(__name__)

# Import redis at module level so tests can patch it.
# Guarded so the module still loads when redis is not installed
# (in-memory fallback is used automatically in that case).
try:
    import redis  # type: ignore
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    _REDIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config (read once at import time, can be patched in tests)
# ---------------------------------------------------------------------------
RATE_LIMIT_REQUESTS   = int(os.environ.get("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW     = int(os.environ.get("RATE_LIMIT_WINDOW",   "60"))
RATE_LIMIT_KEY_PREFIX = os.environ.get("RATE_LIMIT_KEY_PREFIX", "ageval:rl:")


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------
class RedisRateLimiter:
    """
    Sliding fixed-window rate limiter backed by Redis.

    Algorithm: INCR the counter for the current window key, set EXPIRE on
    the first request. Both ops are sent in a pipeline — atomic enough for
    rate-limiting purposes (worst case: two processes start a new window
    simultaneously, both set EXPIRE, no counter is permanently lost).
    """

    def __init__(self, redis_url: str, requests: int, window: int, prefix: str):
        self._pool   = redis.ConnectionPool.from_url(redis_url, decode_responses=True)
        self._r      = redis.Redis(connection_pool=self._pool)
        self.requests = requests
        self.window   = window
        self.prefix   = prefix

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit."""
        redis_key = f"{self.prefix}{key}"
        try:
            pipe = self._r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.window)
            results = pipe.execute()
            count = results[0]
            return count <= self.requests
        except Exception as exc:
            # Redis unavailable — fail open (allow the request)
            log.warning(f"Redis rate-limit check failed, failing open: {exc}")
            return True

    def remaining(self, key: str) -> int:
        """Return how many requests remain in the current window."""
        redis_key = f"{self.prefix}{key}"
        try:
            count = int(self._r.get(redis_key) or 0)
            return max(0, self.requests - count)
        except Exception:
            return self.requests


# ---------------------------------------------------------------------------
# In-memory fallback backend
# ---------------------------------------------------------------------------
class InMemoryRateLimiter:
    """
    Simple fixed-window rate limiter using a Python dict.
    Not shared across processes. Use only as a fallback.
    """

    def __init__(self, requests: int, window: int):
        self.requests = requests
        self.window   = window
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock    = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            ts_list = self._buckets[key]
            # Purge stale timestamps
            cutoff    = now - self.window
            ts_list   = [t for t in ts_list if t > cutoff]
            if len(ts_list) >= self.requests:
                self._buckets[key] = ts_list
                return False
            ts_list.append(now)
            self._buckets[key] = ts_list
            return True

    def remaining(self, key: str) -> int:
        now = time.time()
        with self._lock:
            cutoff = now - self.window
            count  = sum(1 for t in self._buckets.get(key, []) if t > cutoff)
            return max(0, self.requests - count)


# ---------------------------------------------------------------------------
# Public factory — call once at app startup
# ---------------------------------------------------------------------------
_limiter: Optional[RedisRateLimiter | InMemoryRateLimiter] = None
_warned_fallback = False


def get_rate_limiter() -> RedisRateLimiter | InMemoryRateLimiter:
    """
    Return the singleton rate limiter.
    Tries Redis first; falls back to in-memory with a one-time warning.
    """
    global _limiter, _warned_fallback

    if _limiter is not None:
        return _limiter

    redis_url = os.environ.get("REDIS_URL")
    if redis_url and _REDIS_AVAILABLE:
        try:
            limiter = RedisRateLimiter(
                redis_url = redis_url,
                requests  = RATE_LIMIT_REQUESTS,
                window    = RATE_LIMIT_WINDOW,
                prefix    = RATE_LIMIT_KEY_PREFIX,
            )
            # Smoke-test connectivity
            limiter._r.ping()
            log.info(f"Rate limiter: Redis backend connected ({redis_url})")
            _limiter = limiter
            return _limiter
        except Exception as exc:
            if not _warned_fallback:
                log.warning(
                    f"Redis unavailable ({exc}), falling back to in-memory rate limiter. "
                    "This is NOT suitable for multi-process deployments."
                )
                _warned_fallback = True

    if not _warned_fallback and not redis_url:
        log.warning(
            "REDIS_URL not set — using in-memory rate limiter. "
            "Not shared across workers. Set REDIS_URL for production."
        )
        _warned_fallback = True

    _limiter = InMemoryRateLimiter(
        requests = RATE_LIMIT_REQUESTS,
        window   = RATE_LIMIT_WINDOW,
    )
    return _limiter


def reset_limiter_for_testing() -> None:
    """Reset the singleton — for use in tests only."""
    global _limiter, _warned_fallback
    _limiter        = None
    _warned_fallback = False
