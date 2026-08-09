"""Habit ledger: the daily non-negotiables made tickable (HABITS tab).

Definitions come from Daily_protocol.json (via PROTOCOL_PATH); only the ticks
live in the DB. These tests point PROTOCOL_PATH at a fixture so they never
depend on the owner's real protocol file changing.
"""
import json

import pytest

from conftest import freeze

PROTOCOL = {
    "success_bar": "Hitting 70% of days = the system is working.",
    "non_negotiables": [
        {"id": "nn1", "title": "Wake at 7:00", "explanation": "why one"},
        {"id": "nn2", "title": "Outdoor light", "explanation": "why two"},
    ],
}


@pytest.fixture()
def habits_app(tmp_path, monkeypatch, app):
    p = tmp_path / "protocol.json"
    p.write_text(json.dumps(PROTOCOL), encoding="utf-8")
    monkeypatch.setenv("PROTOCOL_PATH", str(p))
    return app


def test_habits_listed_from_protocol_all_untouched(habits_app, client):
    r = client.get("/api/habits")
    assert r.status_code == 200
    d = r.json()
    assert [h["id"] for h in d["habits"]] == ["nn1", "nn2"]
    assert d["done_today"] == 0 and d["total"] == 2
    assert all(h["done"] is False and h["streak"] == 0 for h in d["habits"])
    # 7-day strip, oldest first, ending today
    assert len(d["habits"][0]["week"]) == 7
    assert d["habits"][0]["week"][-1]["date"] == d["date"]


def test_target_pct_parsed_from_success_bar(habits_app, client):
    assert client.get("/api/habits").json()["target_pct"] == 70


def test_target_pct_falls_back_to_70_when_unparseable(habits_app, client,
                                                      monkeypatch, tmp_path):
    p = tmp_path / "no_bar.json"
    p.write_text(json.dumps({"success_bar": "no number here",
                             "non_negotiables": PROTOCOL["non_negotiables"]}),
                 encoding="utf-8")
    monkeypatch.setenv("PROTOCOL_PATH", str(p))
    assert client.get("/api/habits").json()["target_pct"] == 70


def test_toggle_flips_and_persists(habits_app, client):
    assert client.post("/api/habits/nn1/toggle", json={}).json()["done"] is True
    d = client.get("/api/habits").json()
    assert d["done_today"] == 1
    assert [h["done"] for h in d["habits"]] == [True, False]
    # toggling again flips back off
    assert client.post("/api/habits/nn1/toggle", json={}).json()["done"] is False
    assert client.get("/api/habits").json()["done_today"] == 0


def test_toggle_explicit_done_is_idempotent(habits_app, client):
    for _ in range(3):
        assert client.post("/api/habits/nn1/toggle",
                           json={"done": True}).json()["done"] is True
    assert client.get("/api/habits").json()["done_today"] == 1


def test_unknown_habit_404s(habits_app, client):
    assert client.post("/api/habits/nope/toggle", json={}).status_code == 404


def test_streak_counts_consecutive_days(habits_app, client):
    # Tick three consecutive days, then read the streak on the last one.
    for day in ("2026-08-03", "2026-08-04", "2026-08-05"):
        freeze(habits_app, day)
        client.post("/api/habits/nn1/toggle", json={"done": True})
    d = client.get("/api/habits").json()
    assert d["habits"][0]["streak"] == 3


def test_streak_survives_today_not_yet_ticked(habits_app, client):
    """A day only becomes a miss once it's over — an unticked TODAY must not
    zero a streak earned on the preceding days, or every morning would read 0."""
    for day in ("2026-08-03", "2026-08-04"):
        freeze(habits_app, day)
        client.post("/api/habits/nn1/toggle", json={"done": True})
    freeze(habits_app, "2026-08-05")  # today: nothing ticked yet
    d = client.get("/api/habits").json()
    assert d["habits"][0]["done"] is False
    assert d["habits"][0]["streak"] == 2


def test_streak_breaks_on_a_skipped_day(habits_app, client):
    for day in ("2026-08-01", "2026-08-02"):
        freeze(habits_app, day)
        client.post("/api/habits/nn1/toggle", json={"done": True})
    # 2026-08-03 skipped entirely
    freeze(habits_app, "2026-08-04")
    client.post("/api/habits/nn1/toggle", json={"done": True})
    assert client.get("/api/habits").json()["habits"][0]["streak"] == 1


def test_untick_removes_the_day_from_the_streak(habits_app, client):
    for day in ("2026-08-03", "2026-08-04"):
        freeze(habits_app, day)
        client.post("/api/habits/nn1/toggle", json={"done": True})
    client.post("/api/habits/nn1/toggle", json={"done": False})  # untick 08-04
    d = client.get("/api/habits").json()
    assert d["habits"][0]["streak"] == 1  # 08-03 still stands


def test_habits_are_independent(habits_app, client):
    client.post("/api/habits/nn1/toggle", json={"done": True})
    d = client.get("/api/habits").json()
    assert d["habits"][0]["done"] is True
    assert d["habits"][1]["done"] is False
    assert d["done_today"] == 1


def test_empty_protocol_yields_no_habits(app, client, monkeypatch, tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PROTOCOL_PATH", str(p))
    d = client.get("/api/habits").json()
    assert d["habits"] == [] and d["total"] == 0 and d["done_today"] == 0
