"""
tests/test_failures_router.py

Tests for the failure-pattern memory router (api/failures.py), including the
flagship trace→eval loop (POST /v1/failures/{id}/generate-eval). Uses the
in-memory FakeSupabase; auth is bypassed by calling the endpoint functions
directly with an explicit user_id.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.failures as failures
from api.schemas import GenerateEvalRequest
from tests.fakes import FakeSupabase


def _wire(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(failures, "_db", lambda: db)
    return db


def _seed_signature(db, user_id="user_a", episode_id="ep1"):
    db.seed("episodes", [{"episode_id": episode_id, "user_id": user_id,
                          "task": "look up inventory for SKU-42"}])
    ins = db.table("failure_memory").insert({
        "user_id": user_id,
        "agent_id": "agentA",
        "signature": "env_error|inventory|late",
        "label": "inventory environment error (late)",
        "occurrences": 5,
        "sample_episode_id": episode_id,
        "sample_error": "inventory service timed out",
    }).execute()
    return ins.data[0]["id"]


def test_list_failures_scoped_and_ordered(monkeypatch):
    db = _wire(monkeypatch)
    db.table("failure_memory").insert([
        {"user_id": "user_a", "agent_id": "agentA", "signature": "a|x|early", "occurrences": 2},
        {"user_id": "user_a", "agent_id": "agentA", "signature": "b|y|late", "occurrences": 9},
        {"user_id": "user_b", "agent_id": "agentA", "signature": "c|z|mid", "occurrences": 99},
    ]).execute()

    out = failures.list_failures(agent_id=None, user_id="user_a")
    assert [f.occurrences for f in out] == [9, 2]  # most-recurrent first, user-scoped


def test_list_failures_missing_table_returns_empty(monkeypatch):
    db = _wire(monkeypatch)

    def _boom(*a, **k):
        raise Exception("PGRST205: relation not found")

    monkeypatch.setattr(db, "table", _boom)
    assert failures.list_failures(agent_id=None, user_id="user_a") == []


def test_get_failure_returns_occurrences(monkeypatch):
    db = _wire(monkeypatch)
    fid = _seed_signature(db)
    db.seed("failure_occurrences", [
        {"failure_id": fid, "episode_id": "ep1", "step_index": 3, "occurred_at": "2026-06-01"},
        {"failure_id": fid, "episode_id": "ep2", "step_index": 4, "occurred_at": "2026-06-02"},
    ])
    out = failures.get_failure(fid, user_id="user_a")
    assert out["failure"]["signature"] == "env_error|inventory|late"
    assert "centroid" not in out["failure"]  # embedding not leaked
    assert len(out["occurrences"]) == 2


def test_get_failure_404_for_other_user(monkeypatch):
    db = _wire(monkeypatch)
    fid = _seed_signature(db, user_id="user_a")
    with pytest.raises(HTTPException) as exc:
        failures.get_failure(fid, user_id="user_b")
    assert exc.value.status_code == 404


def test_generate_eval_creates_golden_dataset(monkeypatch):
    db = _wire(monkeypatch)
    fid = _seed_signature(db)

    resp = failures.generate_eval(
        fid,
        GenerateEvalRequest(project_id="prj_1"),
        user_id="user_a",
    )
    assert resp.test_case_count == 1
    assert resp.project_id == "prj_1"

    # The golden dataset + one regression test case were persisted.
    ds = db.table("golden_datasets").select("*").eq("id", resp.id).execute()
    assert len(ds.data) == 1
    tcs = db.table("dataset_test_cases").select("*").eq("dataset_id", resp.id).execute()
    assert len(tcs.data) == 1
    tc = tcs.data[0]
    # Input carries the triggering task and provenance back to the failure.
    assert tc["input_data"]["task"] == "look up inventory for SKU-42"
    assert tc["input_data"]["from_failure_signature"] == "env_error|inventory|late"
    # The assertion names the failing tool.
    assert "inventory" in tc["expected_output"]


def test_generate_eval_404_for_unknown_signature(monkeypatch):
    _wire(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        failures.generate_eval(
            "does-not-exist",
            GenerateEvalRequest(project_id="prj_1"),
            user_id="user_a",
        )
    assert exc.value.status_code == 404
