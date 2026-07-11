"""Every gaming vector: the server must stay honest against its own owner."""
import pytest

from conftest import ANSWER, ARTIFACT, gated, make_webm


# ---------- state machine ----------

def test_simple_complete_then_recomplete_409(client):
    tid = client.post("/api/tasks", json={"title": "t", "type": "simple"}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/complete").status_code == 200
    assert client.post(f"/api/tasks/{tid}/complete").status_code == 409


def test_gated_direct_complete_409(client):
    tid = gated(client)
    assert client.post(f"/api/tasks/{tid}/complete").status_code == 409


def test_fourth_gated_task_400(client):
    for i in range(3):
        gated(client, f"g{i}")
    r = client.post("/api/tasks", json={"title": "g4", "type": "gated"})
    assert r.status_code == 400


def test_illegal_transitions_rejected_at_db_layer(app):
    from db import IllegalTransition, SessionLocal, Task
    s = SessionLocal()
    t = Task(date="2026-07-11", title="x", type="gated")
    s.add(t)
    s.commit()
    with pytest.raises(IllegalTransition):
        t.status = "done"          # gated task can never be 'done'
    with pytest.raises(IllegalTransition):
        t.status = "failed_final"  # cannot skip failed_once
    t.status = "passed"            # legal
    with pytest.raises(IllegalTransition):
        t.status = "failed_once"   # passed is terminal
    s.close()


# ---------- gated flow immutability ----------

def _pass_flow(client, mock_llm, tid):
    q = client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    assert q.status_code == 200
    a = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    assert a.status_code == 200
    return a.json()


def test_full_pass_flow(client, mock_llm):
    out = _pass_flow(client, mock_llm, gated(client))
    assert out["status"] == "passed" and out["verdict"] == "PASS"


def test_artifact_swap_after_question_409(client, mock_llm):
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r = client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT + " v2 edit"})
    assert r.status_code == 409


def test_answer_resubmit_409(client, mock_llm):
    tid = gated(client)
    _pass_flow(client, mock_llm, tid)
    r = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER + " but different"})
    assert r.status_code == 409


def test_artifact_after_pass_409(client, mock_llm):
    tid = gated(client)
    _pass_flow(client, mock_llm, tid)
    assert client.post(f"/api/tasks/{tid}/artifact",
                       json={"artifact": ARTIFACT}).status_code == 409


def test_answer_immutable_at_db_layer(app, client, mock_llm):
    tid = gated(client)
    _pass_flow(client, mock_llm, tid)
    from db import ImmutableField, SessionLocal, Task
    s = SessionLocal()
    t = s.get(Task, tid)
    with pytest.raises(ImmutableField):
        t.answer = "rewritten history"
    s.close()


def test_second_retry_locks_and_third_attempt_409(client, mock_llm, app):
    app.llm.evaluate_answer = lambda *a, **k: ("FAIL", "too vague")
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r1 = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER}).json()
    assert r1["status"] == "failed_once" and r1["retry_available"]
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r2 = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER}).json()
    assert r2["status"] == "failed_final" and not r2["retry_available"]
    assert client.post(f"/api/tasks/{tid}/artifact",
                       json={"artifact": ARTIFACT}).status_code == 409


def test_retry_then_pass(client, mock_llm, app):
    verdicts = iter([("FAIL", "vague"), ("PASS", "specific")])
    app.llm.evaluate_answer = lambda *a, **k: next(verdicts)
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    out = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER}).json()
    assert out["status"] == "passed" and out["attempts"] == 2


# ---------- input validation ----------

def test_artifact_under_200_chars_422(client, mock_llm):
    r = client.post(f"/api/tasks/{gated(client)}/artifact", json={"artifact": "SVD notes"})
    assert r.status_code == 422 and mock_llm["question"] == 0


def test_answer_under_100_chars_422(client, mock_llm):
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r = client.post(f"/api/tasks/{tid}/answer", json={"answer": "it just works"})
    assert r.status_code == 422 and mock_llm["eval"] == 0


def test_answer_copied_from_artifact_422(client, mock_llm):
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r = client.post(f"/api/tasks/{tid}/answer", json={"answer": ARTIFACT[:150]})
    assert r.status_code == 422 and "copied" in r.json()["detail"]
    assert mock_llm["eval"] == 0  # rejected before any LLM spend


# ---------- LLM fails closed ----------

def test_unparseable_llm_output_503_task_untouched(client, mock_llm, app):
    app.llm.evaluate_answer = mock_llm["real_evaluate_answer"]  # real parser
    app.llm._chat = lambda *a, **k: "Sounds good, marking complete!"
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    r = client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    assert r.status_code == 503
    t = client.get("/api/tasks").json()["tasks"][0]
    assert t["status"] == "open" and t["attempts"] == 0 and t["answer"] == ""


def test_llm_unreachable_on_artifact_503(client, mock_llm, app):
    def boom(_, **kw):
        raise app.llm.LLMError("evaluator unreachable")
    app.llm.generate_question = boom
    tid = gated(client)
    r = client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    assert r.status_code == 503
    t = client.get("/api/tasks").json()["tasks"][0]
    assert t["status"] == "open" and t["artifact"] == "" and t["question"] == ""


def test_verdict_parser_is_strict(app):
    import llm as llm_mod
    for bad in ["PASS", "verdict: pass — ok", "VERDICT PASS ok", "",
                "VERDICT: MAYBE — hmm"]:
        assert llm_mod.VERDICT_RE.search(bad) is None
    m = llm_mod.VERDICT_RE.search("VERDICT: FAIL — hedged without committing")
    assert m.group(1) == "FAIL"


# ---------- verbal gate ----------

def test_short_recording_rejected_400(client, mock_llm, tmp_path):
    f = make_webm(tmp_path / "short.webm", 10)
    r = client.post("/api/recordings",
                    files={"file": ("s.webm", f.read_bytes(), "audio/webm")})
    assert r.status_code == 400 and "minimum is 4:30" in r.json()["detail"]


def test_garbage_upload_400(client, mock_llm):
    r = client.post("/api/recordings",
                    files={"file": ("g.webm", b"\x00" * 4096, "audio/webm")})
    assert r.status_code == 400


def test_recording_flow_and_viewed_gate(client, mock_llm, tmp_path, app, monkeypatch):
    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "um so basically")
    f = make_webm(tmp_path / "ok.webm", 271)
    r = client.post("/api/recordings",
                    files={"file": ("ok.webm", f.read_bytes(), "audio/webm")})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get("/api/tasks").json()["verbal"]["done"] is False
    assert client.post(f"/api/recordings/{rid}/viewed").status_code == 200
    assert client.get("/api/tasks").json()["verbal"]["done"] is True


def test_viewed_before_audit_exists_409(app, client):
    from db import Recording, SessionLocal
    s = SessionLocal()
    r = Recording(date="2026-07-11", duration_sec=300, audio_path="x",
                  transcript_path="x", audit_path="/nonexistent/audit.md")
    s.add(r)
    s.commit()
    rid = r.id
    s.close()
    assert client.post(f"/api/recordings/{rid}/viewed").status_code == 409
