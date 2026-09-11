"""Durable task handoffs, the compact review overview API, and the
backend-authoritative session-task link."""
import datetime as dt

from conftest import ANSWER, ARTIFACT, freeze, gated


def _pass_gated(client, title="Recall me"):
    task_id = gated(client, title)
    assert client.post(f"/api/tasks/{task_id}/artifact", json={"artifact": ARTIFACT}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/answer", json={"answer": ANSWER}).status_code == 200
    return task_id


def test_continuation_is_durable_and_never_rewrites_submitted_answer(client, app, mock_llm):
    task_id = gated(client, "Continue a proof")
    assert client.put(f"/api/tasks/{task_id}/continuation", json={
        "state": "paused", "next_step": "Work through the rank-deficient case",
        "blocker": "", "tried": "Derived the full-rank version first"}).status_code == 200

    # Make this task receive a submitted (but retryable) answer, then ensure a
    # later handoff update leaves that evidence exactly as written.
    app.llm.evaluate_answer = lambda *_args, **_kw: ("FAIL", "missing edge case")
    assert client.post(f"/api/tasks/{task_id}/artifact", json={"artifact": ARTIFACT}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/answer", json={"answer": ANSWER}).status_code == 200
    out = client.put(f"/api/tasks/{task_id}/continuation", json={
        "state": "stuck", "next_step": "Find a counterexample",
        "blocker": "I cannot connect the null space to the solution set",
        "tried": "Re-read the normal equations"})
    assert out.status_code == 200
    task = out.json()
    assert task["answer"] == ANSWER
    assert task["continuation_state"] == "stuck"
    assert task["next_step"] == "Find a counterexample"
    assert task["blocker"].startswith("I cannot")

    # A fresh request exercises persistence rather than returning an in-memory row.
    saved = next(t for t in client.get("/api/tasks").json()["tasks"] if t["id"] == task_id)
    assert saved["tried"] == "Re-read the normal equations"
    assert saved["answer"] == ANSWER


def test_continuation_rejects_invalid_stuck_and_closed_tasks(client, mock_llm):
    task_id = client.post("/api/tasks", json={"title": "Read notes", "type": "simple"}).json()["id"]
    assert client.put(f"/api/tasks/{task_id}/continuation", json={
        "state": "stuck", "next_step": "", "blocker": "", "tried": ""}).status_code == 422
    assert client.put(f"/api/tasks/{task_id}/continuation", json={
        "state": "later", "next_step": "", "blocker": "", "tried": ""}).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/complete").status_code == 200
    assert client.put(f"/api/tasks/{task_id}/continuation", json={
        "state": "paused", "next_step": "No longer needed", "blocker": "", "tried": ""}).status_code == 409


def test_carry_forward_preserves_source_and_is_idempotent(client, app):
    freeze(app, "2026-07-13")
    source_id = client.post("/api/tasks", json={"title": "Study SVD", "type": "gated"}).json()["id"]
    assert client.put(f"/api/tasks/{source_id}/continuation", json={
        "state": "stuck", "next_step": "Prove the rank-deficient extension",
        "blocker": "The basis extension is unclear", "tried": "Worked a 2x2 example"}).status_code == 200

    first = client.post(f"/api/tasks/{source_id}/carry-forward").json()
    successor = first["task"]
    assert first["already_carried_forward"] is False
    assert successor["date"] == "2026-07-14"
    assert successor["id"] != source_id
    assert successor["status"] == "open" and successor["attempts"] == 0
    assert successor["continuation_state"] == "active"
    assert successor["next_step"] == "Prove the rank-deficient extension"
    assert successor["blocker"] == "The basis extension is unclear"
    assert successor["carried_from_task_id"] == source_id

    # The old record remains a faithful account of what happened on the 13th.
    source = next(t for t in client.get("/api/tasks?date=2026-07-13").json()["tasks"]
                  if t["id"] == source_id)
    assert source["continuation_state"] == "stuck"
    assert source["carried_from_task_id"] is None

    second = client.post(f"/api/tasks/{source_id}/carry-forward").json()
    assert second["already_carried_forward"] is True
    assert second["task"]["id"] == successor["id"]
    assert len(client.get("/api/tasks?date=2026-07-14").json()["tasks"]) == 1


def test_carry_forward_rejects_closed_and_noncurrent_tasks(client, app):
    freeze(app, "2026-07-13")
    done_id = client.post("/api/tasks", json={"title": "Done", "type": "simple"}).json()["id"]
    client.post(f"/api/tasks/{done_id}/complete")
    assert client.post(f"/api/tasks/{done_id}/carry-forward").status_code == 409

    old_id = client.post("/api/tasks", json={"title": "Old", "type": "simple", "date": "2026-07-12"}).json()["id"]
    assert client.post(f"/api/tasks/{old_id}/carry-forward").status_code == 409


def test_review_overview_is_safe_and_reflects_existing_fsrs_schedule(client, app, mock_llm):
    freeze(app, "2026-07-13")
    task_id = _pass_gated(client, "Understand the SVD")
    initial = client.get("/api/reviews/overview").json()
    assert initial["next_due"] is None and initial["upcoming"] == [] and initial["completed"] == []
    assert initial["due"] == [{"id": initial["due"][0]["id"], "source_task_id": task_id,
                               "title": "Understand the SVD", "due_date": "2026-07-13",
                               "overdue": False}]
    assert "artifact" not in initial["due"][0]

    review_id = initial["due"][0]["id"]
    client.post(f"/api/reviews/{review_id}/reveal")
    graded = client.post(f"/api/reviews/{review_id}/grade", json={"grade": "recalled"}).json()
    expected_next = (dt.date(2026, 7, 13) + dt.timedelta(days=2)).isoformat()
    assert graded["next_due"] == expected_next

    freeze(app, "2026-07-14")
    between = client.get("/api/reviews/overview").json()
    assert between["due"] == [] and between["next_due"] == expected_next
    assert between["upcoming"][0]["due_date"] == expected_next
    assert between["completed"][0]["grade"] == "recalled"
    assert between["completed"][0]["source_task_id"] == task_id

    freeze(app, "2026-07-16")
    overdue = client.get("/api/reviews/overview").json()
    assert overdue["next_due"] is None
    assert overdue["due"][0]["due_date"] == expected_next
    assert overdue["due"][0]["overdue"] is True


def test_session_task_link_is_backend_authoritative(client):
    """A running session's task is a real column, not something the client has
    to reconstruct from its own cache — recovering it after a delayed/missed
    client-side write (e.g. a request outlived by a cold-start gap) must not
    silently drop the link, which used to hide the live timer entirely."""
    task_id = client.post("/api/tasks", json={"title": "Derive SVD", "type": "gated"}).json()["id"]
    sess = client.post("/api/sessions/start",
                       json={"kind": "struggle_timer", "planned_minutes": 20,
                             "task_id": task_id}).json()
    assert sess["task_id"] == task_id

    # A second client with no local cache at all (e.g. a fresh reload after a
    # cold start) must still recover the exact same link from the backend.
    current = client.get("/api/sessions/current").json()
    assert current["id"] == sess["id"]
    assert current["task_id"] == task_id


def test_session_without_task_id_stays_untethered(client):
    """Not every session kind is tied to one task — omitting task_id must not
    error, and must round-trip as null rather than some sentinel value."""
    sess = client.post("/api/sessions/start",
                       json={"kind": "verbal_prep", "planned_minutes": 5}).json()
    assert sess["task_id"] is None
    assert client.get("/api/sessions/current").json()["task_id"] is None
