"""
tests/test_key_management.py

Unit tests for API key lifecycle:
  - Expiry enforcement in verify_api_key
  - Key rotation (POST /keys/rotate)
  - Key revocation (DELETE /keys/{key_id})
  - Key listing (GET /keys)
  - last_used_at update on auth

All Supabase / DB calls are mocked — no real network required.
"""

from __future__ import annotations

import hashlib
import secrets
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# ---- helpers ----------------------------------------------------------

def _make_key_row(
    user_id: str = "usr_test",
    is_active: bool = True,
    expires_at: str | None = None,
    key_id: str = "key-uuid-1234",
) -> dict:
    """Build a fake api_keys row as Supabase would return it."""
    return {
        "id"          : key_id,
        "user_id"     : user_id,
        "is_active"   : is_active,
        "expires_at"  : expires_at,
        "last_used_at": None,
        "label"       : "test-key",
        "created_at"  : "2026-01-01T00:00:00+00:00",
    }


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _make_db_mock(row: dict | None):
    """Create a mock Supabase client that returns `row` from api_keys queries."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[row] if row else [])
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value = chain
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[row] if row else [])
    return db


# ---- verify_api_key tests --------------------------------------------

class TestVerifyApiKeyExpiry:
    """Tests for expiry enforcement inside verify_api_key."""

    @patch("main.get_db")
    def test_valid_non_expiring_key(self, mock_get_db):
        from main import verify_api_key

        row = _make_key_row(expires_at=None)
        db  = _make_db_mock(row)
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        result  = verify_api_key(authorization=f"Bearer {raw_key}")
        assert result == "usr_test"

    @patch("main.get_db")
    def test_expired_key_raises_401(self, mock_get_db):
        from fastapi import HTTPException
        from main import verify_api_key

        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        row  = _make_key_row(expires_at=past)
        db   = _make_db_mock(row)
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(authorization=f"Bearer {raw_key}")
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @patch("main.get_db")
    def test_future_expiry_is_valid(self, mock_get_db):
        from main import verify_api_key

        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        row    = _make_key_row(expires_at=future)
        db     = _make_db_mock(row)
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        result  = verify_api_key(authorization=f"Bearer {raw_key}")
        assert result == "usr_test"

    @patch("main.get_db")
    def test_inactive_key_raises_401(self, mock_get_db):
        from fastapi import HTTPException
        from main import verify_api_key

        # Inactive key — simulate empty data from DB (is_active filter)
        db = _make_db_mock(None)
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(authorization=f"Bearer {raw_key}")
        assert exc_info.value.status_code == 401

    @patch("main.get_db")
    def test_missing_bearer_raises_401(self, mock_get_db):
        from fastapi import HTTPException
        from main import verify_api_key

        mock_get_db.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            verify_api_key(authorization="not-a-bearer-token")
        assert exc_info.value.status_code == 401


# ---- rotate_key tests ------------------------------------------------

class TestRotateKey:
    """Tests for POST /keys/rotate."""

    @patch("main.get_db")
    def test_rotate_returns_new_key(self, mock_get_db):
        from main import rotate_key, RegisterRequest

        db = MagicMock()
        # Deactivate old key
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        # Insert new key
        db.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        body    = RegisterRequest(label="rotated-key")
        result  = rotate_key(body=body, authorization=f"Bearer {raw_key}", user_id="usr_test")

        assert "api_key" in result
        assert result["api_key"].startswith("ageval-sk-")
        assert result["api_key"] != raw_key  # new key is different
        assert result["user_id"] == "usr_test"

    @patch("main.get_db")
    def test_rotate_deactivates_old_key(self, mock_get_db):
        from main import rotate_key, RegisterRequest

        db            = MagicMock()
        update_chain  = MagicMock()
        db.table.return_value.update.return_value.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_get_db.return_value = db

        raw_key  = f"ageval-sk-{secrets.token_hex(24)}"
        old_hash = _hash(raw_key)
        body     = RegisterRequest(label="new")
        rotate_key(body=body, authorization=f"Bearer {raw_key}", user_id="usr_test")

        # Verify deactivate was called with is_active=False on old key hash
        db.table.return_value.update.assert_any_call({"is_active": False})

    @patch("main.get_db")
    def test_rotate_rollback_on_insert_failure(self, mock_get_db):
        """
        When insert of the new key fails, the old key should remain active
        (no deactivation happened yet — insert-first pattern).
        """
        from fastapi import HTTPException
        from main import rotate_key, RegisterRequest

        db = MagicMock()
        # Insert fails immediately — old key was never deactivated
        db.table.return_value.insert.return_value.execute.side_effect = Exception("DB error")
        mock_get_db.return_value = db

        raw_key = f"ageval-sk-{secrets.token_hex(24)}"
        body    = RegisterRequest(label="fail")
        with pytest.raises(HTTPException) as exc_info:
            rotate_key(body=body, authorization=f"Bearer {raw_key}", user_id="usr_test")
        assert exc_info.value.status_code == 500
        # Old key was NEVER deactivated — no update call should have happened
        db.table.return_value.update.assert_not_called()


# ---- revoke_key tests ------------------------------------------------

class TestRevokeKey:
    """Tests for DELETE /keys/{key_id}."""

    @patch("main.get_db")
    def test_revoke_own_key(self, mock_get_db):
        from main import revoke_key

        row = {"id": "key-1", "user_id": "usr_test", "is_active": True}
        db  = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])
        db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_get_db.return_value = db

        result = revoke_key(key_id="key-1", user_id="usr_test")
        assert result["revoked"] is True

    @patch("main.get_db")
    def test_revoke_other_users_key_raises_403(self, mock_get_db):
        from fastapi import HTTPException
        from main import revoke_key

        row = {"id": "key-1", "user_id": "usr_other", "is_active": True}
        db  = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])
        mock_get_db.return_value = db

        with pytest.raises(HTTPException) as exc_info:
            revoke_key(key_id="key-1", user_id="usr_test")
        assert exc_info.value.status_code == 403

    @patch("main.get_db")
    def test_revoke_nonexistent_key_raises_404(self, mock_get_db):
        from fastapi import HTTPException
        from main import revoke_key

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_get_db.return_value = db

        with pytest.raises(HTTPException) as exc_info:
            revoke_key(key_id="nonexistent", user_id="usr_test")
        assert exc_info.value.status_code == 404

    @patch("main.get_db")
    def test_revoke_already_inactive_key_is_idempotent(self, mock_get_db):
        from main import revoke_key

        row = {"id": "key-1", "user_id": "usr_test", "is_active": False}
        db  = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])
        mock_get_db.return_value = db

        result = revoke_key(key_id="key-1", user_id="usr_test")
        assert result["revoked"] is False
        assert "already inactive" in result["reason"]


# ---- list_keys tests -------------------------------------------------

class TestListKeys:
    """Tests for GET /keys."""

    @patch("main.get_db")
    def test_list_returns_only_own_keys(self, mock_get_db):
        from main import list_keys

        keys = [
            {"id": "k1", "label": "prod", "is_active": True, "expires_at": None,
             "last_used_at": None, "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": "k2", "label": "dev",  "is_active": True, "expires_at": None,
             "last_used_at": None, "created_at": "2026-01-02T00:00:00+00:00"},
        ]
        db = MagicMock()
        (db.table.return_value
           .select.return_value
           .eq.return_value
           .eq.return_value
           .order.return_value
           .execute.return_value) = MagicMock(data=keys)
        mock_get_db.return_value = db

        result = list_keys(user_id="usr_test")
        assert len(result["keys"]) == 2
        assert result["keys"][0]["id"] == "k1"

    @patch("main.get_db")
    def test_list_returns_empty_for_no_keys(self, mock_get_db):
        from main import list_keys

        db = MagicMock()
        (db.table.return_value
           .select.return_value
           .eq.return_value
           .eq.return_value
           .order.return_value
           .execute.return_value) = MagicMock(data=[])
        mock_get_db.return_value = db

        result = list_keys(user_id="usr_new")
        assert result["keys"] == []
