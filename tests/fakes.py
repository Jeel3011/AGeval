"""
tests/fakes.py

In-memory test double for the Supabase client.

It implements the subset of the supabase-py fluent API that AGeval's server,
merger and scorers actually use, backed by plain Python dicts. This lets the
real production code paths (merger.run_merger, eval.rules.score_episode,
eval.llm_judge.judge_episode, the FastAPI endpoints) run end-to-end without a
live Postgres — useful for tests and for the `examples/prove_*` proof scripts.

Supported chain:
    client.table("t").select("*").eq("c", v).in_("c", [..]).lt("c", v)
          .order("c", desc=True).limit(n).range(a, b).execute()
    client.table("t").insert(row|rows).execute()
    client.table("t").update({...}).eq("c", v).execute()
    client.table("t").upsert(row|rows, on_conflict="a,b").execute()
    client.rpc("fn", {...}).execute()
"""

from __future__ import annotations

import itertools
from typing import Any


class _Result:
    def __init__(self, data: list[dict] | dict | None, count: int | None = None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, store: "FakeSupabase", table: str):
        self._store = store
        self._table = table
        self._rows = store._tables.setdefault(table, [])
        self._filters: list = []
        self._op: str | None = None
        self._payload: Any = None
        self._on_conflict: list[str] | None = None
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._count_mode: str | None = None

    # ---- read shaping -----------------------------------------------------
    def select(self, *_cols, count: str | None = None):
        self._op = self._op or "select"
        self._count_mode = count
        return self

    def eq(self, col, val):
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, values):
        vs = set(values)
        self._filters.append(lambda r: r.get(col) in vs)
        return self

    def lt(self, col, val):
        self._filters.append(lambda r: r.get(col) is not None and r.get(col) < val)
        return self

    def gte(self, col, val):
        self._filters.append(lambda r: r.get(col) is not None and r.get(col) >= val)
        return self

    def order(self, col, desc: bool = False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    # ---- writes -----------------------------------------------------------
    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict.split(",") if on_conflict else None
        return self

    def delete(self):
        self._op = "delete"
        return self

    # ---- execution --------------------------------------------------------
    def _matches(self, row) -> bool:
        return all(f(row) for f in self._filters)

    def execute(self) -> _Result:
        if self._op in ("select", None):
            rows = [r for r in self._rows if self._matches(r)]
            if self._order:
                col, desc = self._order
                rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
            total = len(rows)
            if self._range is not None:
                a, b = self._range
                rows = rows[a : b + 1]
            if self._limit is not None:
                rows = rows[: self._limit]
            return _Result([dict(r) for r in rows], count=total if self._count_mode else None)

        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for row in payload:
                row = dict(row)
                row.setdefault("id", str(next(self._store._ids)))
                self._rows.append(row)
                inserted.append(dict(row))
            return _Result(inserted)

        if self._op == "update":
            updated = []
            for row in self._rows:
                if self._matches(row):
                    row.update(self._payload)
                    updated.append(dict(row))
            return _Result(updated)

        if self._op == "upsert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            result = []
            for row in payload:
                row = dict(row)
                existing = None
                if self._on_conflict:
                    for r in self._rows:
                        if all(r.get(k) == row.get(k) for k in self._on_conflict):
                            existing = r
                            break
                if existing is not None:
                    existing.update(row)
                    result.append(dict(existing))
                else:
                    row.setdefault("id", str(next(self._store._ids)))
                    self._rows.append(row)
                    result.append(dict(row))
            return _Result(result)

        if self._op == "delete":
            kept = [r for r in self._rows if not self._matches(r)]
            removed = len(self._rows) - len(kept)
            self._rows[:] = kept
            return _Result([], count=removed)

        return _Result([])


class FakeSupabase:
    """Minimal in-memory stand-in for a supabase-py client."""

    def __init__(self):
        self._tables: dict[str, list[dict]] = {}
        self._ids = itertools.count(1)
        self._rpc_handlers: dict = {}

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def seed(self, table: str, rows: list[dict]) -> None:
        self._tables.setdefault(table, []).extend(dict(r) for r in rows)

    def register_rpc(self, name: str, handler) -> None:
        self._rpc_handlers[name] = handler

    def rpc(self, name: str, params: dict | None = None):
        handler = self._rpc_handlers.get(name)
        data = handler(params or {}) if handler else None

        class _Rpc:
            def execute(_self):
                return _Result(data)

        return _Rpc()
