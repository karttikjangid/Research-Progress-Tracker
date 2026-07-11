"""H2 regression: timezone correctness at IST day boundaries.

Freezes clock.now_utc at 00:30 IST and 23:30 IST (the window where UTC and the
IST civil date disagree) and asserts day boundaries, FSRS scheduling, streak
overdue, ISO-week grace, auto-close and backup naming all use the LOCAL date.
"""
import datetime as dt

from conftest import ANSWER, ARTIFACT, gated

UTC = dt.timezone.utc


def _freeze(app, monkeypatch, when_utc):
    monkeypatch.setattr(app.clock, "now_utc", lambda: when_utc)


# 00:30 IST on 2026-07-12  ==  19:00 UTC on 2026-07-11 (dates disagree)
MIDNIGHT_IST = dt.datetime(2026, 7, 11, 19, 0, tzinfo=UTC)
# 23:30 IST on 2026-07-12  ==  18:00 UTC on 2026-07-12 (dates agree)
LATE_IST = dt.datetime(2026, 7, 12, 18, 0, tzinfo=UTC)


def test_today_local_is_ist_date_not_utc(client, app, monkeypatch):
    _freeze(app, monkeypatch, MIDNIGHT_IST)
    assert app.today() == "2026-07-12"          # IST, not UTC's 2026-07-11
    assert app.clock.today_local() == "2026-07-12"


def _pass_and_reveal(client, app):
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    due = client.get("/api/reviews/due").json()
    rev = due[0]["id"]
    client.post(f"/api/reviews/{rev}/reveal")
    return tid, rev


def test_fsrs_chained_due_is_local_date_at_00_30_ist(client, app, mock_llm, monkeypatch):
    _freeze(app, monkeypatch, MIDNIGHT_IST)
    _tid, rev = _pass_and_reveal(client, app)
    out = client.post(f"/api/reviews/{rev}/grade", json={"grade": "recalled"}).json()
    # recalled→Good→+2 days in LOCAL terms: 2026-07-12 + 2 = 2026-07-14
    # (the pre-fix bug stored card.due.date() in UTC = 2026-07-13, a day early)
    assert out["next_due"] == "2026-07-14", out


def test_fsrs_chained_due_is_local_date_at_23_30_ist(client, app, mock_llm, monkeypatch):
    _freeze(app, monkeypatch, LATE_IST)
    _tid, rev = _pass_and_reveal(client, app)
    out = client.post(f"/api/reviews/{rev}/grade", json={"grade": "recalled"}).json()
    assert out["next_due"] == "2026-07-14", out  # 2026-07-12 + 2, local


def test_day_close_and_backup_use_local_date_at_00_30_ist(client, app, monkeypatch):
    _freeze(app, monkeypatch, MIDNIGHT_IST)
    client.post("/api/tasks", json={"title": "t", "type": "simple"})
    client.post("/api/day/close")
    from db import DayLog, SessionLocal
    s = SessionLocal()
    row = s.get(DayLog, "2026-07-12")   # keyed to LOCAL date, not UTC 2026-07-11
    s.close()
    assert row is not None
    assert (app.infra.BACKUP_DIR / "2026-07-12").exists()   # backup named by local date
    assert not (app.infra.BACKUP_DIR / "2026-07-11").exists()


def test_overdue_uses_local_dates_at_boundary(client, app, monkeypatch):
    _freeze(app, monkeypatch, MIDNIGHT_IST)          # local today = 2026-07-12
    from db import Review, SessionLocal
    s = SessionLocal()
    s.add(Review(source_task_id=999, due_date="2026-07-09",   # 3 local days overdue
                 fsrs_card_state="{}", status="due"))
    s.commit()
    s.close()
    # timer honored + no failed_final, but a review >2 days overdue → not a streak day
    out = client.post("/api/day/close", json={"timer_honored": True}).json()
    assert out["current_streak"] == 0        # broken by the overdue debt, computed on local dates


def test_iso_week_grace_resets_across_week_boundary(client, app, monkeypatch):
    # Sat 2026-07-11 honored → streak 1; Sun 07-12 miss → grace (week 28);
    # Mon 07-13 miss → NEW ISO week → fresh grace token, streak survives (not 0).
    assert dt.date(2026, 7, 12).isocalendar()[1] != dt.date(2026, 7, 13).isocalendar()[1]
    _freeze(app, monkeypatch, dt.datetime(2026, 7, 11, 6, 30, tzinfo=UTC))  # noon IST Sat
    a = client.post("/api/day/close", json={"timer_honored": True}).json()
    assert a["current_streak"] == 1
    _freeze(app, monkeypatch, dt.datetime(2026, 7, 12, 18, 0, tzinfo=UTC))  # 23:30 IST Sun
    b = client.post("/api/day/close", json={"timer_honored": False}).json()
    assert b["current_streak"] == 1          # grace of week 28 consumed, survives
    _freeze(app, monkeypatch, dt.datetime(2026, 7, 12, 19, 0, tzinfo=UTC))  # 00:30 IST Mon
    c = client.post("/api/day/close", json={"timer_honored": False}).json()
    assert c["current_streak"] == 1          # week 29 has its own grace → still survives


def test_auto_close_stale_session_uses_utc_duration_at_boundary(client, app, monkeypatch):
    _freeze(app, monkeypatch, LATE_IST)      # 23:30 IST
    r = client.post("/api/sessions/start",
                    json={"kind": "struggle_timer", "planned_minutes": 30})
    assert r.status_code == 201
    _freeze(app, monkeypatch, LATE_IST + dt.timedelta(hours=7))  # +7h, crosses midnight
    # >6h straggler is swept before the concurrency check, so a new start succeeds
    r2 = client.post("/api/sessions/start", json={"kind": "decode", "planned_minutes": 10})
    assert r2.status_code == 201
