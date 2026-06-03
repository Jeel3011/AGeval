"""
tests/test_datasets_router.py

Tests for the Supabase-backed datasets router. Uses the in-memory FakeSupabase
so the real DB code path runs without a live Postgres. Auth is bypassed by
calling the endpoint functions directly with an explicit user_id.
"""

from __future__ import annotations

import api.datasets as datasets
from api.schemas import DatasetCreate, TestCase as _TestCase  # aliased: avoid pytest collection
from tests.fakes import FakeSupabase


def _wire(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(datasets, "_db", lambda: db)
    return db


def test_create_and_list_dataset(monkeypatch):
    db = _wire(monkeypatch)

    payload = DatasetCreate(
        project_id="prj_1",
        name="Support Queries",
        version="v2",
        test_cases=[
            _TestCase(input_data={"q": "where is my order"}, expected_output="tracking link"),
            _TestCase(input_data={"q": "refund please"}, expected_output="refund flow"),
        ],
    )
    created = datasets.create_dataset(payload, user_id="user_a")
    assert created.test_case_count == 2
    assert created.name == "Support Queries"
    assert created.last_updated == "just now"

    # Listing returns it with the real test-case count.
    out = datasets.get_datasets(project_id="prj_1", user_id="user_a")
    assert len(out) == 1
    assert out[0].test_case_count == 2

    # The test cases were actually persisted.
    rows = db.table("dataset_test_cases").select("*").eq("dataset_id", created.id).execute()
    assert len(rows.data) == 2


def test_datasets_scoped_per_user(monkeypatch):
    _wire(monkeypatch)
    datasets.create_dataset(
        DatasetCreate(project_id="prj_1", name="A", test_cases=[]),
        user_id="user_a",
    )
    # user_b sees nothing.
    assert datasets.get_datasets(project_id="prj_1", user_id="user_b") == []
    # user_a sees their own.
    assert len(datasets.get_datasets(project_id="prj_1", user_id="user_a")) == 1


def test_list_empty_for_new_project(monkeypatch):
    _wire(monkeypatch)
    assert datasets.get_datasets(project_id="prj_unknown", user_id="user_a") == []
