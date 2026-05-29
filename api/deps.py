"""
api/deps.py

Shared FastAPI dependencies for the sub-routers.

These thin wrappers exist to break the import cycle with main.py: main.py imports
the routers at the bottom of the module (after auth is defined), so the routers
cannot import from main at their own module top. The dependency below imports
from main lazily — at request time, when main is fully initialised — so router
endpoints can require the same authentication as the core endpoints.
"""

from __future__ import annotations

from fastapi import Header


def verify_api_key(authorization: str = Header(...)) -> str:
    """Authenticate a request using the same logic as the core API.

    Returns the authenticated ``user_id`` (so routers can scope data) and raises
    401 on a missing/invalid/expired key.
    """
    from main import verify_api_key as _verify  # lazy import avoids circular import

    return _verify(authorization=authorization)
