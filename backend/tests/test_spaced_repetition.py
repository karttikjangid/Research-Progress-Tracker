"""Spaced repetition (FSRS, self-graded) + the quality streak.

The review flow is enforced server-side in one direction (reveal → grade) and
the streak is computed ONLY at day-close. LLM is mocked; time is frozen wherever
a date actually matters (scheduling, streak weeks)."""
import datetime as dt
import json

import pytest

from conftest import ANSWER, ARTIFACT, gated


# ---------- helpers ----------

def pass_gated(client, title="Recall me"):
    """Drive a gated task to `passed` (mock_llm returns PASS), seeding review #1."""
    tid = gated(client, title)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    return tid


def all_reviews(client):
    return client.get("/api/reviews/due?date=2999-12-31").json()


def open_review_for(client, tid):
    return next(r["id"] for r in all_reviews(client) if r["source_task_id"] == tid)


def freeze(app, date_str, hour=12):
    d = dt.date.fromisoformat(date_str)
    app.today = lambda: date_str
    app._now = lambda: dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.timezone.utc)


# ---------- the enforced order ----------

def test_first_review_created_on_pass_due_today(client, mock_llm):
    pass_gated(client, "Derive SVD")
    due = client.get("/api/reviews/due").json()
    assert len(due) == 1 and due[0]["title"] == "Derive SVD"
    assert due[0]["due_date"] and due[0]["overdue"] is False


def test_due_list_is_title_only_reveal_returns_content(client, mock_llm):
    pass_gated(client, "Secret proof")
    item = client.get("/api/reviews/due").json()[0]
    assert item["title"] == "Secret proof"
    for leaked in ("artifact", "question", "answer", "fsrs_card_state"):
        assert leaked not in item
    rev = client.post(f"/api/reviews/{item['id']}/reveal").json()
    assert rev["artifact"] == ARTIFACT and rev["question"] and rev["answer"] == ANSWER
    assert rev["revealed_at"]


def test_grade_without_reveal_409(client, mock_llm):
    pass_gated(client)
    rid = client.get("/api/reviews/due").json()[0]["id"]
    r = client.post(f"/api/reviews/{rid}/grade", json={"grade": "recalled"})
    assert r.status_code == 409
    # nothing recorded
    assert client.get("/api/reviews/due").json()[0]["id"] == rid


def test_grade_immutable_once_written(client, mock_llm):
    pass_gated(client)
    rid = client.get("/api/reviews/due").json()[0]["id"]
    client.post(f"/api/reviews/{rid}/reveal")
    assert client.post(f"/api/reviews/{rid}/grade", json={"grade": "recalled"}).status_code == 200
    assert client.post(f"/api/reviews/{rid}/grade", json={"grade": "partial"}).status_code == 409
    from db import ImmutableField, Review, SessionLocal
    s = SessionLocal()
    r = s.get(Review, rid)
    with pytest.raises(ImmutableField):
        r.grade = "forgot"  # db-layer backstop, same pattern as Task.answer
    s.close()


def test_invalid_grade_value_422(client, mock_llm):
    pass_gated(client)
    rid = client.get("/api/reviews/due").json()[0]["id"]
    client.post(f"/api/reviews/{rid}/reveal")
    assert client.post(f"/api/reviews/{rid}/grade", json={"grade": "meh"}).status_code == 422


# ---------- FSRS scheduling + chain + retire ----------

def test_grade_mapping_produces_day_scale_due_dates(client, mock_llm):
    """recalled→Good→+2d, partial→Hard→+1d, forgot→Again→+1d from a fresh card."""

    def next_due(grade):
        tid = pass_gated(client, f"card-{grade}")
        rid = open_review_for(client, tid)
        client.post(f"/api/reviews/{rid}/reveal")
        return client.post(f"/api/reviews/{rid}/grade", json={"grade": grade}).json()["next_due"]

    # scheduling is relative to the (real, unfrozen) grade instant; assert the
    # gap in days rather than an absolute date so the test is time-agnostic.
    today = dt.date.today()
    gap = lambda d: (dt.date.fromisoformat(d) - today).days
    assert gap(next_due("recalled")) == 2
    assert gap(next_due("partial")) == 1
    assert gap(next_due("forgot")) == 1


def test_fsrs_state_persists_and_evolves_across_three_review_chain(client, mock_llm):
    tid = pass_gated(client, "Chain")
    from db import Review, SessionLocal
    for i, g in enumerate(["recalled", "partial", "recalled"]):
        rid = open_review_for(client, tid)
        client.post(f"/api/reviews/{rid}/reveal")
        out = client.post(f"/api/reviews/{rid}/grade", json={"grade": g}).json()
        assert out["retired"] is (i == 2)  # retires on the 3rd
    # exactly 3 rows, and the stored FSRS card state actually evolved
    s = SessionLocal()
    revs = s.query(Review).filter(Review.source_task_id == tid).order_by(Review.id).all()
    states = [json.loads(r.fsrs_card_state) for r in revs]
    s.close()
    assert [r.grade for r in revs] == ["recalled", "partial", "recalled"]
    assert len(revs) == 3
    assert states[0]["stability"] is None                 # review #1 = brand-new card
    assert states[1]["stability"] is not None             # #2 scheduled from a reviewed card
    assert states[2]["stability"] != states[1]["stability"]
    # retired: no fourth review exists
    assert not any(r["source_task_id"] == tid for r in all_reviews(client))


def test_forgot_grade_spawns_one_recall_gated_task(client, mock_llm):
    pass_gated(client, "Derive SVD")
    rid = client.get("/api/reviews/due").json()[0]["id"]
    client.post(f"/api/reviews/{rid}/reveal")
    out = client.post(f"/api/reviews/{rid}/grade", json={"grade": "forgot"}).json()
    assert out["recall_task_id"]
    tasks = client.get("/api/tasks").json()["tasks"]
    recall = next(t for t in tasks if t["id"] == out["recall_task_id"])
    assert recall["title"] == "RECALL: Derive SVD"
    assert recall["type"] == "gated" and recall["status"] == "open"


def test_non_forgot_grades_spawn_no_recall_task(client, mock_llm):
    tid = pass_gated(client, "Keep")
    rid = open_review_for(client, tid)
    client.post(f"/api/reviews/{rid}/reveal")
    out = client.post(f"/api/reviews/{rid}/grade", json={"grade": "recalled"}).json()
    assert out["recall_task_id"] is None
    assert not any(t["title"].startswith("RECALL:")
                   for t in client.get("/api/tasks").json()["tasks"])


def test_recall_task_is_exempt_from_gated_cap(client, mock_llm):
    # `Cap` is normal gated #1 (passed). A forgot review spawns a RECALL task that
    # must NOT count toward the 3/day cap, so two more normal gated tasks still fit.
    pass_gated(client, "Cap")
    rid = client.get("/api/reviews/due").json()[0]["id"]
    client.post(f"/api/reviews/{rid}/reveal")
    client.post(f"/api/reviews/{rid}/grade", json={"grade": "forgot"})
    assert client.post("/api/tasks", json={"title": "g1", "type": "gated"}).status_code == 201
    assert client.post("/api/tasks", json={"title": "g2", "type": "gated"}).status_code == 201
    assert client.post("/api/tasks", json={"title": "g3", "type": "gated"}).status_code == 400


def test_overdue_review_rolls_forward_and_counts(client, mock_llm):
    from db import Review, SessionLocal
    s = SessionLocal()
    s.add(Review(source_task_id=999, due_date="2020-01-01",
                 fsrs_card_state="{}", status="due"))
    s.commit()
    s.close()
    due = client.get("/api/reviews/due").json()
    old = next(r for r in due if r["due_date"] == "2020-01-01")
    assert old["overdue"] is True and old["title"] == "(task removed)"
    assert client.get("/api/tasks").json()["reviews_due"] >= 1


def test_due_count_in_tasks_and_ping_line(client, mock_llm):
    pass_gated(client)
    assert client.get("/api/tasks").json()["reviews_due"] == 1
    line = client.post("/api/day/close").json()["summary_line"]
    assert "1 reviews due" in line and "streak" in line


# ---------- streak: truth table (each condition failing independently) ----------

def test_streak_day_truth_table(app):
    import main
    from db import Review, SessionLocal, Task
    s = SessionLocal()
    good = "2026-07-15"
    # all three conditions satisfied → streak-day
    assert main._streak_values(s, good, True)["streak_day"] is True
    # (1) timer not honored, nothing else wrong → not a streak-day
    assert main._streak_values(s, good, False)["streak_day"] is False
    # (2) a gated task ended failed_final on that day (isolated on its own date)
    d2 = "2026-07-16"
    t = Task(date=d2, title="x", type="gated")
    s.add(t)
    s.commit()
    t.status = "failed_once"
    t.status = "failed_final"
    s.commit()
    assert main._streak_values(s, d2, True)["streak_day"] is False
    assert main._streak_values(s, good, True)["streak_day"] is True  # other days unaffected
    # (3) a review overdue by >2 days is a global debt → breaks the streak-day
    s.add(Review(source_task_id=1, due_date="2026-07-10",
                 fsrs_card_state="{}", status="due"))  # cutoff for 07-15 is 07-13
    s.commit()
    assert main._streak_values(s, good, True)["streak_day"] is False
    s.close()  # the >2-day boundary is asserted in the dedicated boundary test


def test_overdue_boundary_is_strictly_greater_than_two_days(app):
    import main
    from db import Review, SessionLocal
    s = SessionLocal()
    s.add(Review(source_task_id=1, due_date="2026-07-13",
                 fsrs_card_state="{}", status="due"))
    s.commit()
    # close 07-15: cutoff 07-13; due 07-13 is NOT < 07-13 → still a streak-day
    assert main._streak_values(s, "2026-07-15", True)["streak_day"] is True
    # close 07-16: cutoff 07-14; due 07-13 < 07-14 → overdue >2d → breaks
    assert main._streak_values(s, "2026-07-16", True)["streak_day"] is False
    s.close()


# ---------- streak: grace token (per ISO week) ----------

def _close(client, timer):
    return client.post("/api/day/close", json={"timer_honored": timer}).json()


def _daylog(app, date):
    from db import DayLog, SessionLocal
    s = SessionLocal()
    row = s.get(DayLog, date)
    out = (row.streak_day, row.grace_used, row.current_streak, row.longest_streak)
    s.close()
    return out


def test_grace_consumed_once_per_week_resets_next_week_breaks_on_second_miss(app, client):
    # ISO week A = 2026-07-13(Mon)…07-19; week B starts 2026-07-20(Mon).
    freeze(app, "2026-07-13")
    assert _close(client, True)["current_streak"] == 1

    freeze(app, "2026-07-14")  # first miss of week A → grace consumed, streak survives
    r = _close(client, False)
    assert r["current_streak"] == 1
    assert _daylog(app, "2026-07-14")[1] is True   # grace_used

    freeze(app, "2026-07-15")  # second miss same week → break
    r = _close(client, False)
    assert r["current_streak"] == 0
    assert _daylog(app, "2026-07-15")[1] is False  # not a grace day — a break

    freeze(app, "2026-07-20")  # new ISO week, honored → rebuild
    assert _close(client, True)["current_streak"] == 1

    freeze(app, "2026-07-21")  # fresh weekly grace token available again
    r = _close(client, False)
    assert r["current_streak"] == 1
    assert _daylog(app, "2026-07-21")[1] is True


def test_longest_streak_is_high_water_mark(app, client):
    for i, d in enumerate(["2026-07-13", "2026-07-14", "2026-07-15"]):
        freeze(app, d)
        _close(client, True)
    assert _daylog(app, "2026-07-15")[2:] == (3, 3)  # current, longest
    freeze(app, "2026-07-16")  # timer miss #1 this week → grace, survives at 3
    _close(client, False)
    freeze(app, "2026-07-17")  # miss #2 → break to 0, longest stays 3
    _close(client, False)
    assert _daylog(app, "2026-07-17")[2:] == (0, 3)
    assert client.get("/api/streak").json() == {"current_streak": 0, "longest_streak": 3}


def test_day_close_idempotent_with_streak_and_timer_persisted(app, client):
    freeze(app, "2026-07-13")
    r1 = _close(client, False)   # non-streak (timer), first miss → grace
    r2 = client.post("/api/day/close").json()   # bare re-close: timer must persist
    assert r2["already_closed"] is True
    assert r2["current_streak"] == r1["current_streak"]
    # only one ping despite two closes
    assert len(app.infra.PUBLIC_LOG.read_text().splitlines()) == 1
