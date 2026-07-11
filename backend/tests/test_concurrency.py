"""C1 regression: concurrent-request atomicity.

Runs the REAL app under uvicorn on the test's on-disk SQLite file (not
in-memory) and fires simultaneous requests from a thread pool — the exact
shape of review_report.md's C1 reproduction. Pre-fix these raced; post-fix
exactly one request may win each contested transition.
"""
import concurrent.futures as cf
import threading
import time

import pytest
import requests

from conftest import ANSWER, ARTIFACT, gated


@pytest.fixture()
def server(app, mock_llm):
    """A real uvicorn server in a background thread, sharing the app's on-disk
    DB. Yields (main_module, base_url)."""
    import uvicorn
    config = uvicorn.Config(app.app, host="127.0.0.1", port=0,
                            log_level="error", lifespan="on")
    srv = uvicorn.Server(config)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(500):
        if srv.started and srv.servers:
            break
        time.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):  # wait until it actually answers
        try:
            requests.get(f"{base}/api/tasks", timeout=2)
            break
        except requests.RequestException:
            time.sleep(0.01)
    yield app, base
    srv.should_exit = True
    th.join(timeout=5)


def _fire(n, url, payloads):
    """POST `n` requests concurrently; return the list of status codes."""
    def go(body):
        return requests.post(url, json=body, timeout=10).status_code
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(go, payloads))


def test_concurrent_answers_one_wins(server):
    app, base = server
    tid = gated(requests_client(base))
    requests.post(f"{base}/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    codes = _fire(6, f"{base}/api/tasks/{tid}/answer",
                  [{"answer": f"{ANSWER} variant {i}"} for i in range(6)])
    assert codes.count(200) == 1, f"expected exactly one 200, got {codes}"
    assert set(codes) == {200, 409}, f"losers must be clean 409s, got {codes}"

    s = app.SessionLocal()
    try:
        t = s.get(app.Task, tid)
        n_answers = s.query(app.Answer).filter(app.Answer.task_id == tid).count()
    finally:
        s.close()
    assert t.attempts == 1, f"attempts must be 1, got {t.attempts}"
    assert n_answers == 1, f"exactly one stored answer, got {n_answers}"
    assert t.status == "passed"


def test_concurrent_artifacts_one_wins(server):
    app, base = server
    tid = gated(requests_client(base))
    codes = _fire(6, f"{base}/api/tasks/{tid}/artifact",
                  [{"artifact": f"{ARTIFACT} take {i}"} for i in range(6)])
    assert codes.count(200) == 1, f"expected exactly one 200, got {codes}"
    assert set(codes) == {200, 409}, f"losers must be clean 409s, got {codes}"

    s = app.SessionLocal()
    try:
        t = s.get(app.Task, tid)
    finally:
        s.close()
    assert t.question != "" and t.artifact != ""   # exactly one question opened
    assert t.answer == "" and t.attempts == 0       # no answer consumed yet


def test_concurrent_grades_one_wins(server):
    app, base = server
    # seed a review by passing a gated task, then reveal it
    tid = gated(requests_client(base))
    requests.post(f"{base}/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    requests.post(f"{base}/api/tasks/{tid}/answer", json={"answer": ANSWER})
    due = requests.get(f"{base}/api/reviews/due").json()
    rev_id = due[0]["id"]
    requests.post(f"{base}/api/reviews/{rev_id}/reveal")

    codes = _fire(6, f"{base}/api/reviews/{rev_id}/grade",
                  [{"grade": "recalled"} for _ in range(6)])
    assert codes.count(200) == 1, f"expected exactly one 200, got {codes}"
    assert set(codes) == {200, 409}, f"losers must be clean 409s, got {codes}"

    s = app.SessionLocal()
    try:
        revs = s.query(app.Review).filter(
            app.Review.source_task_id == tid).all()
        graded = [r for r in revs if r.grade]
        due_now = [r for r in revs if r.status == "due"]
    finally:
        s.close()
    assert len(graded) == 1, f"exactly one grade recorded, got {len(graded)}"
    # exactly one chained review created (not six) → no duplicate side effects
    assert len(due_now) == 1, f"one chained review, got {len(due_now)}"


# --- tiny shim so conftest.gated() (which expects a TestClient) works over HTTP
class requests_client:
    def __init__(self, base):
        self.base = base

    def post(self, path, json=None, **kw):
        return requests.post(f"{self.base}{path}", json=json, timeout=10)
