"""
tests/test_rate_limiter.py

Unit tests for the Redis and in-memory rate limiter backends.
These tests never need a real Redis server — the Redis backend is tested
via monkeypatching; the in-memory backend is tested directly.
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import MagicMock, patch

import rate_limiter as rl_module
from rate_limiter import (
    InMemoryRateLimiter,
    RedisRateLimiter,
    reset_limiter_for_testing,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test starts with a fresh rate-limiter singleton."""
    reset_limiter_for_testing()
    yield
    reset_limiter_for_testing()


# ---------------------------------------------------------------------------
# InMemoryRateLimiter tests
# ---------------------------------------------------------------------------
class TestInMemoryRateLimiter:
    def test_allows_requests_under_limit(self):
        lim = InMemoryRateLimiter(requests=5, window=60)
        for _ in range(5):
            assert lim.is_allowed("user-a") is True

    def test_blocks_request_over_limit(self):
        lim = InMemoryRateLimiter(requests=3, window=60)
        for _ in range(3):
            lim.is_allowed("user-a")
        assert lim.is_allowed("user-a") is False

    def test_different_keys_are_independent(self):
        lim = InMemoryRateLimiter(requests=2, window=60)
        lim.is_allowed("user-a")
        lim.is_allowed("user-a")
        # user-a is now at limit; user-b should still be allowed
        assert lim.is_allowed("user-a") is False
        assert lim.is_allowed("user-b") is True

    def test_window_expiry_resets_counter(self):
        lim = InMemoryRateLimiter(requests=2, window=1)  # 1-second window
        lim.is_allowed("user-a")
        lim.is_allowed("user-a")
        assert lim.is_allowed("user-a") is False
        # Wait for the window to expire
        time.sleep(1.1)
        assert lim.is_allowed("user-a") is True

    def test_remaining_counts_correctly(self):
        lim = InMemoryRateLimiter(requests=10, window=60)
        assert lim.remaining("user-a") == 10
        lim.is_allowed("user-a")
        lim.is_allowed("user-a")
        assert lim.remaining("user-a") == 8

    def test_remaining_never_negative(self):
        lim = InMemoryRateLimiter(requests=2, window=60)
        for _ in range(5):
            lim.is_allowed("over-limit")
        assert lim.remaining("over-limit") == 0

    def test_thread_safety(self):
        """Rapid concurrent calls must not corrupt state."""
        import threading
        lim     = InMemoryRateLimiter(requests=1000, window=60)
        results = []
        lock    = threading.Lock()

        def hammer():
            for _ in range(100):
                r = lim.is_allowed("shared-key")
                with lock:
                    results.append(r)

        threads = [threading.Thread(target=hammer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed = sum(1 for r in results if r)
        assert allowed == 1000  # exactly the limit
        assert len(results) == 1000


# ---------------------------------------------------------------------------
# RedisRateLimiter tests (mocked Redis)
# ---------------------------------------------------------------------------
class TestRedisRateLimiter:
    def _make_mock_redis(self, counter_value: int):
        """Build a mock redis client whose pipeline returns counter_value."""
        mock_redis = MagicMock()
        mock_pipe  = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value   = [counter_value, True]  # [INCR result, EXPIRE result]
        mock_redis.get.return_value      = str(counter_value)
        mock_redis.ping.return_value     = True
        return mock_redis

    @patch("rate_limiter.redis")
    def test_allows_under_limit(self, mock_redis_module):
        mock_r = self._make_mock_redis(counter_value=50)
        mock_redis_module.ConnectionPool.from_url.return_value = MagicMock()
        mock_redis_module.Redis.return_value = mock_r

        lim = RedisRateLimiter("redis://localhost", requests=100, window=60, prefix="test:")
        lim._r = mock_r
        assert lim.is_allowed("user-a") is True

    @patch("rate_limiter.redis")
    def test_blocks_at_limit(self, mock_redis_module):
        mock_r = self._make_mock_redis(counter_value=101)
        lim    = RedisRateLimiter("redis://localhost", requests=100, window=60, prefix="test:")
        lim._r = mock_r
        assert lim.is_allowed("user-a") is False

    @patch("rate_limiter.redis")
    def test_fails_open_on_redis_error(self, mock_redis_module):
        """If Redis is unreachable, the limiter should allow the request (fail open)."""
        mock_r = MagicMock()
        mock_r.pipeline.side_effect = Exception("Connection refused")
        lim    = RedisRateLimiter("redis://localhost", requests=100, window=60, prefix="test:")
        lim._r = mock_r
        assert lim.is_allowed("user-a") is True  # fail open

    @patch("rate_limiter.redis")
    def test_remaining_computed_correctly(self, mock_redis_module):
        mock_r = self._make_mock_redis(counter_value=30)
        lim    = RedisRateLimiter("redis://localhost", requests=100, window=60, prefix="test:")
        lim._r = mock_r
        assert lim.remaining("user-a") == 70


# ---------------------------------------------------------------------------
# Factory / singleton tests
# ---------------------------------------------------------------------------
class TestGetRateLimiter:
    def test_returns_in_memory_without_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        limiter = rl_module.get_rate_limiter()
        assert isinstance(limiter, InMemoryRateLimiter)

    def test_singleton_returns_same_instance(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        a = rl_module.get_rate_limiter()
        b = rl_module.get_rate_limiter()
        assert a is b

    def test_falls_back_to_memory_if_redis_unavailable(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://nonexistent-host:6379/0")
        limiter = rl_module.get_rate_limiter()
        # Should fall back to InMemoryRateLimiter without raising
        assert isinstance(limiter, InMemoryRateLimiter)
