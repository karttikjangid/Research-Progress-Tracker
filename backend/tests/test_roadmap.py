"""Roadmap ticket state: mark done / edit deadline / reset (ROADMAP page).

The plan (topics, deadlines) comes from roadmap.json via ROADMAP_PATH; only the
mutable per-ticket state (done, deadline override) lives in the DB. These tests
point ROADMAP_PATH at a fixture so they never depend on the real plan file.
"""
import json

import pytest

ROADMAP = {
    "meta": {"owner": "Test", "goal": "Ship it", "window": "2026-01-01 to 2026-06-01"},
    "phases": [
        {"id": "A", "name": "Phase A", "tickets": [
            {"id": "A1", "topic": "First thing", "deadline": "2026-02-01"},
            {"id": "A2", "topic": "Second thing", "deadline": "2026-03-01"},
        ]},
    ],
}


@pytest.fixture()
def rm_app(tmp_path, monkeypatch, app):
    p = tmp_path / "roadmap.json"
    p.write_text(json.dumps(ROADMAP), encoding="utf-8")
    monkeypatch.setenv("ROADMAP_PATH", str(p))
    return app


def _ticket(client, tid):
    for p in client.get("/api/roadmap").json()["phases"]:
        for t in p["tickets"]:
            if t["id"] == tid:
                return t
    raise AssertionError(f"no ticket {tid}")


def test_plan_defaults_when_no_state(rm_app, client):
    t = _ticket(client, "A1")
    assert t["status"] == "open"
    assert t["deadline"] == "2026-02-01"
    assert t["plan_deadline"] == "2026-02-01"
    assert t["done_date"] == ""


def test_mark_done_and_reopen(rm_app, client):
    r = client.post("/api/roadmap/tickets/A1", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    t = _ticket(client, "A1")
    assert t["status"] == "done" and t["done_date"] == rm_app.today()
    # reopen clears the done date
    client.post("/api/roadmap/tickets/A1", json={"status": "open"})
    assert _ticket(client, "A1")["done_date"] == ""


def test_deadline_override(rm_app, client):
    client.post("/api/roadmap/tickets/A1", json={"deadline": "2026-05-15"})
    t = _ticket(client, "A1")
    assert t["deadline"] == "2026-05-15"       # effective = override
    assert t["plan_deadline"] == "2026-02-01"  # plan preserved for revert


def test_deadline_clear_means_no_deadline(rm_app, client):
    client.post("/api/roadmap/tickets/A1", json={"deadline": ""})
    assert _ticket(client, "A1")["deadline"] == ""  # explicit no-deadline


def test_revert_deadline_restores_plan(rm_app, client):
    client.post("/api/roadmap/tickets/A1", json={"deadline": "2026-05-15"})
    client.post("/api/roadmap/tickets/A1", json={"revert_deadline": True})
    assert _ticket(client, "A1")["deadline"] == "2026-02-01"


def test_status_and_deadline_in_one_call(rm_app, client):
    client.post("/api/roadmap/tickets/A2",
                json={"status": "done", "deadline": "2026-04-01"})
    t = _ticket(client, "A2")
    assert t["status"] == "done" and t["deadline"] == "2026-04-01"


def test_bad_date_422(rm_app, client):
    assert client.post("/api/roadmap/tickets/A1",
                       json={"deadline": "not-a-date"}).status_code == 422


def test_bad_status_422(rm_app, client):
    assert client.post("/api/roadmap/tickets/A1",
                       json={"status": "sideways"}).status_code == 422


def test_unknown_ticket_404(rm_app, client):
    assert client.post("/api/roadmap/tickets/ZZ",
                       json={"status": "done"}).status_code == 404


def test_reset_clears_everything(rm_app, client):
    client.post("/api/roadmap/tickets/A1", json={"status": "done"})
    client.post("/api/roadmap/tickets/A2", json={"deadline": "2026-05-15"})
    r = client.post("/api/roadmap/reset", json={})
    assert r.status_code == 200 and r.json()["reset"] == 2
    for tid in ("A1", "A2"):
        t = _ticket(client, tid)
        assert t["status"] == "open"
        assert t["deadline"] == ""       # no deadline → never overdue
        assert t["done_date"] == ""


def test_empty_roadmap_still_ok(app, client, monkeypatch, tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ROADMAP_PATH", str(p))
    assert client.get("/api/roadmap").json() == {"meta": None, "phases": []}
    # mutating a ticket that doesn't exist in an empty plan 404s
    assert client.post("/api/roadmap/tickets/A1",
                       json={"status": "done"}).status_code == 404
