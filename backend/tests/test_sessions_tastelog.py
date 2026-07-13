"""Work sessions (timed blocks + auto-close), the immutable tastelog, the raw
verdict tally, and their inclusion in the day-close ping and export.

Time is frozen via main._now / main.today wherever a duration or date matters."""
import datetime as dt

import pytest

UTC = dt.timezone.utc


def at(app, iso):
    """Freeze the clock: iso like '2026-07-13T09:00:00+00:00'."""
    d = dt.datetime.fromisoformat(iso)
    app._now = lambda: d
    app.today = lambda: d.date().isoformat()


TL_LINE = "Training arm felt clean; eval arm dragged and I dreaded every minute."
UNDERSTOOD = "I can now derive the SVD from the spectral theorem without notes."


# ---------- sessions: concurrency + duration ----------

def test_second_concurrent_session_409(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    assert client.post("/api/sessions/start",
                       json={"kind": "struggle_timer", "planned_minutes": 20}).status_code == 201
    r = client.post("/api/sessions/start", json={"kind": "decode", "planned_minutes": 10})
    assert r.status_code == 409


def test_end_computes_actual_minutes_server_side(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    sid = client.post("/api/sessions/start",
                      json={"kind": "decode", "planned_minutes": 30}).json()["id"]
    at(app, "2026-07-13T09:42:00+00:00")
    out = client.post(f"/api/sessions/{sid}/end").json()
    assert out["actual_minutes"] == 42.0 and out["aborted"] is False and out["ended_at"]
    assert client.post(f"/api/sessions/{sid}/end").status_code == 409  # end twice


def test_invalid_kind_and_planned_422(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    assert client.post("/api/sessions/start",
                       json={"kind": "nap", "planned_minutes": 10}).status_code == 422
    assert client.post("/api/sessions/start",
                       json={"kind": "decode", "planned_minutes": 0}).status_code == 422


# ---------- sessions: auto-close ----------

def test_open_session_auto_closed_on_startup(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    sid = client.post("/api/sessions/start",
                      json={"kind": "struggle_timer", "planned_minutes": 20}).json()["id"]
    at(app, "2026-07-13T09:05:00+00:00")
    app._close_orphan_sessions()  # simulates the next server startup
    from db import SessionLocal, WorkSession
    s = SessionLocal()
    sess = s.get(WorkSession, sid)
    got = (sess.aborted, sess.abort_trigger, bool(sess.ended_at))
    s.close()
    assert got == (True, "auto_close", True)


def test_session_older_than_6h_swept_before_concurrency_check(client, app):
    at(app, "2026-07-13T02:00:00+00:00")
    old = client.post("/api/sessions/start",
                      json={"kind": "eval_arm", "planned_minutes": 60}).json()["id"]
    at(app, "2026-07-13T09:00:01+00:00")  # 7h later
    # the stale session must be auto-aborted, so a new one starts cleanly (no 409)
    assert client.post("/api/sessions/start",
                       json={"kind": "decode", "planned_minutes": 15}).status_code == 201
    from db import SessionLocal, WorkSession
    s = SessionLocal()
    got = (s.get(WorkSession, old).aborted, s.get(WorkSession, old).abort_trigger)
    s.close()
    assert got == (True, "auto_close")


# ---------- timer_honored propagation ----------

def _struggle(client, app, date, actual, planned):
    at(app, f"{date}T09:00:00+00:00")
    sid = client.post("/api/sessions/start",
                      json={"kind": "struggle_timer", "planned_minutes": planned}).json()["id"]
    at(app, (dt.datetime.fromisoformat(f"{date}T09:00:00+00:00")
             + dt.timedelta(minutes=actual)).isoformat())
    client.post(f"/api/sessions/{sid}/end")
    at(app, f"{date}T23:00:00+00:00")


def test_met_struggle_timer_sets_timer_honored_and_streak(client, app):
    _struggle(client, app, "2026-07-13", actual=25, planned=20)
    out = client.post("/api/day/close").json()
    assert out["current_streak"] == 1  # timer_honored True → streak-day
    from db import DayLog, SessionLocal
    s = SessionLocal()
    assert s.get(DayLog, "2026-07-13").timer_honored is True
    s.close()


def test_short_struggle_timer_does_not_honor(client, app):
    _struggle(client, app, "2026-07-13", actual=12, planned=20)
    out = client.post("/api/day/close").json()
    assert out["current_streak"] == 0  # actual < planned → not honored → not a streak-day
    from db import DayLog, SessionLocal
    s = SessionLocal()
    assert s.get(DayLog, "2026-07-13").timer_honored is False
    s.close()


def test_non_struggle_kind_does_not_honor(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    sid = client.post("/api/sessions/start",
                      json={"kind": "training_arm", "planned_minutes": 20}).json()["id"]
    at(app, "2026-07-13T10:00:00+00:00")  # 60 min, well over plan, but wrong kind
    client.post(f"/api/sessions/{sid}/end")
    at(app, "2026-07-13T23:00:00+00:00")
    assert client.post("/api/day/close").json()["current_streak"] == 0


# ---------- tastelog: validation + immutability ----------

def test_tastelog_field_bounds(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    # understood is required, 10–500 chars; 422s land before any row is written
    assert client.post("/api/tastelog", json={"understood": "x" * 9}).status_code == 422
    assert client.post("/api/tastelog", json={"understood": "x" * 501}).status_code == 422
    # a sticking point, when given, shares the 10-char floor
    assert client.post("/api/tastelog",
                       json={"understood": "x" * 20, "sticking_point": "short"}).status_code == 422
    # understood alone (no sticking point) is valid and is the first row to land
    assert client.post("/api/tastelog", json={"understood": "y" * 10}).status_code == 201


def test_history_surfaces_reflection(client, app):
    at(app, "2026-07-13T21:00:00+00:00")
    client.post("/api/tastelog", json={
        "understood": "The SVD falls straight out of the spectral theorem now.",
        "sticking_point": "Rank-deficiency and the Gram-Schmidt basis extension."})
    # a reflection-only day (no task/recording) still appears in History...
    day = next(d for d in client.get("/api/history").json() if d["date"] == "2026-07-13")
    assert day["reflection"]["understood"].startswith("The SVD")
    assert "Gram-Schmidt" in day["reflection"]["sticking_point"]
    # ...but the reflection anchor task is never surfaced as a task
    assert day["tasks"] == []


def test_tastelog_immutable_once_written(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    assert client.post("/api/tastelog", json={"understood": UNDERSTOOD}).status_code == 201
    # second POST for the same date is refused
    assert client.post("/api/tastelog",
                       json={"understood": UNDERSTOOD + " changed"}).status_code == 409
    # db-layer backstop, same pattern as Task.answer
    from db import ImmutableField, SessionLocal, TasteLog
    s = SessionLocal()
    tl = s.get(TasteLog, "2026-07-13")
    with pytest.raises(ImmutableField):
        tl.understood = "rewritten"
    s.close()
    assert client.get("/api/tastelog?date=2026-07-13").json()["understood"] == UNDERSTOOD


def test_sticking_point_schedules_review_next_day(client, app):
    at(app, "2026-07-13T21:00:00+00:00")
    r = client.post("/api/tastelog", json={
        "understood": "Finally see why A^T A is positive semi-definite.",
        "sticking_point": "Why rank-deficiency forces Gram-Schmidt to extend the basis."})
    assert r.status_code == 201
    # the reflection anchor is invisible among the day's real tasks
    assert client.get("/api/tasks?date=2026-07-13").json()["tasks"] == []
    # nothing due the day it is written; exactly one retrieval due the next day
    assert client.get("/api/reviews/due?date=2026-07-13").json() == []
    due = client.get("/api/reviews/due?date=2026-07-14").json()
    assert len(due) == 1 and due[0]["title"].startswith("STICKING POINT —")
    # reveal surfaces the sticking-point text; grading advances FSRS and closes it
    rev = client.post(f"/api/reviews/{due[0]['id']}/reveal").json()
    assert "Gram-Schmidt" in rev["artifact"]
    graded = client.post(f"/api/reviews/{due[0]['id']}/grade", json={"grade": "partial"}).json()
    assert graded["status"] == "done"


def test_get_tastelog_absent_is_null(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    assert client.get("/api/tastelog?date=2026-07-13").json() is None


# ---------- verdict: raw tallies over both arms, range-scoped ----------

def _seed_verdict(app):
    from db import SessionLocal, TasteLog, WorkSession
    s = SessionLocal()
    s.add_all([
        TasteLog(date="2026-07-13", drift_arm="training", dread_arm="eval", one_liner=TL_LINE),
        TasteLog(date="2026-07-14", drift_arm="eval", dread_arm="training", one_liner=TL_LINE),
        # outside the query window — must be excluded from the tallies
        TasteLog(date="2026-07-20", drift_arm="training", dread_arm="training", one_liner=TL_LINE),
        WorkSession(date="2026-07-13", kind="struggle_timer", planned_minutes=20,
                    actual_minutes=30.0, started_at="s", ended_at="e", aborted=False),
        WorkSession(date="2026-07-14", kind="eval_arm", planned_minutes=45,
                    actual_minutes=45.0, started_at="s", ended_at="e", aborted=False),
        WorkSession(date="2026-07-14", kind="training_arm", planned_minutes=60,
                    actual_minutes=10.0, started_at="s", ended_at="e",
                    aborted=True, abort_trigger="auto_close"),
    ])
    s.commit()
    s.close()


def test_verdict_is_raw_tallies_only(client, app):
    _seed_verdict(app)
    v = client.get("/api/tastelog/verdict?from=2026-07-13&to=2026-07-14").json()
    assert v["drift"] == {"training": 1, "eval": 1, "none": 0}   # 07-20 row excluded
    assert v["dread"] == {"training": 1, "eval": 1, "none": 0}
    assert v["aborted_sessions"] == 1
    assert v["actual_minutes_by_kind"] == {"struggle_timer": 30.0, "eval_arm": 45.0,
                                           "training_arm": 10.0}
    # evidence only: no scores/weights/recommendation keys leak in
    assert set(v) == {"from", "to", "drift", "dread", "aborted_sessions",
                      "actual_minutes_by_kind"}


def test_verdict_bad_dates_422(client, app):
    assert client.get("/api/tastelog/verdict?from=nope").status_code == 422


# ---------- day-close flag + export inclusion ----------

def test_day_close_flags_missing_tastelog(client, app):
    at(app, "2026-07-13T09:00:00+00:00")
    sid = client.post("/api/sessions/start",
                      json={"kind": "decode", "planned_minutes": 15}).json()["id"]
    at(app, "2026-07-13T09:20:00+00:00")
    client.post(f"/api/sessions/{sid}/end")
    at(app, "2026-07-13T23:00:00+00:00")
    assert "TASTELOG MISSING" in client.post("/api/day/close").json()["summary_line"]
    # add the tastelog, re-close → flag gone (line changed, so a fresh close)
    client.post("/api/tastelog", json={"understood": UNDERSTOOD})
    assert "TASTELOG MISSING" not in client.post("/api/day/close").json()["summary_line"]


def test_export_includes_sessions_and_tastelog(client, app):
    _seed_verdict(app)
    body = client.get("/api/export?from=2026-07-13&to=2026-07-20").text
    assert "- [session:struggle_timer] 30.0/20 min" in body
    assert "ABORTED (auto_close)" in body
    assert "- [tastelog] drift→training, dread→eval:" in body
