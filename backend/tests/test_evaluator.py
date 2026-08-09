"""Evaluator integrity: audit trail, freshness, harder retries, stats,
vocab ledger, drift review — and one full simulated week."""
from conftest import ANSWER, ARTIFACT, freeze, gated, make_webm


def _capture_chat(app, monkeypatch, reply):
    """Mock the transport, keep the real prompt-building logic."""
    seen = []

    def fake_chat(system, user, **kw):
        seen.append({"system": system, "user": user})
        return reply(len(seen)) if callable(reply) else reply
    monkeypatch.setattr(app.llm, "_chat", fake_chat)
    return seen


# ---------- audit trail ----------

def test_every_llm_call_is_persisted(client, app, monkeypatch):
    _capture_chat(app, monkeypatch,
                  lambda n: "Q?" if n == 1 else "VERDICT: PASS — specific")
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    from db import LLMCall, SessionLocal
    s = SessionLocal()
    calls = s.query(LLMCall).order_by(LLMCall.id).all()
    s.close()
    assert [c.purpose for c in calls] == ["question_gen", "answer_eval"]
    assert calls[0].task_id == tid and len(calls[0].prompt_hash) == 16
    assert calls[1].parsed_verdict == "PASS" and "VERDICT" in calls[1].response


def test_failed_llm_call_is_persisted_too(client, app, monkeypatch):
    def dead(system, user, **kw):
        raise app.llm.LLMError("evaluator unreachable")
    monkeypatch.setattr(app.llm, "_chat", dead)
    tid = gated(client)
    assert client.post(f"/api/tasks/{tid}/artifact",
                       json={"artifact": ARTIFACT}).status_code == 503
    from db import LLMCall, SessionLocal
    s = SessionLocal()
    row = s.query(LLMCall).one()
    s.close()
    assert row.response.startswith("ERROR:")


# ---------- question freshness + harder retry ----------

def test_question_freshness_includes_prior_similar_questions(client, app, monkeypatch):
    seen = _capture_chat(app, monkeypatch,
                         lambda n: f"Q{n}?" if n % 2 else "VERDICT: PASS — ok")
    t1 = gated(client, "Derive SVD from spectral theorem")
    client.post(f"/api/tasks/{t1}/artifact", json={"artifact": ARTIFACT})
    assert "DIFFERENT aspect" not in seen[0]["user"]  # nothing to avoid yet

    t2 = gated(client, "Verify SVD numerically on rank-deficient A")
    client.post(f"/api/tasks/{t2}/artifact", json={"artifact": ARTIFACT})
    assert "Q1?" in seen[1]["user"] and "DIFFERENT aspect" in seen[1]["user"]


def test_retry_question_targets_named_weakness(client, app, monkeypatch):
    replies = iter(["Q1?", "VERDICT: FAIL — never justified the n=1 edge case",
                    "Q2 harder?"])
    seen = _capture_chat(app, monkeypatch, lambda n: next(replies))
    tid = gated(client)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    retry_prompt = seen[2]["user"]
    assert "STRICTLY HARDER" in retry_prompt
    assert "never justified the n=1 edge case" in retry_prompt


# ---------- deterministic stats ----------

def test_compute_stats_fixture(app):
    text = ("um so basically the gradient is like the transpose thing "
            "you know and um actually it just works " * 5).strip()
    st = app.transcribe.compute_stats(text, 300)  # 5 minutes
    assert st["wpm"] == 18.0            # 90 words / 5 min
    assert st["fillers_per_min"] == 6.0  # (um*2+like+basically+you know+actually)*5 = 30/5
    assert 0 < st["unique_ratio"] < 0.25  # heavy repetition
    assert st["longest_silence_sec"] is None  # no segment timing without whisper


def test_stats_stored_and_injected_into_audit(client, app, monkeypatch, tmp_path):
    seen = _capture_chat(app, monkeypatch, "AUDIT: too many fillers")
    monkeypatch.setattr(app.transcribe, "transcribe",
                        lambda p: "um um like basically the svd " * 20)
    f = make_webm(tmp_path / "ok.webm", 271)
    r = client.post("/api/recordings",
                    files={"file": ("ok.webm", f.read_bytes(), "audio/webm")}).json()
    assert r["wpm"] and r["fillers_per_min"] > 0
    audit_prompt = seen[0]["user"]
    assert "argue from these numbers" in audit_prompt
    assert "fillers_per_min" in audit_prompt


# ---------- vocabulary ledger ----------

def test_vocab_flags_accumulate_and_feed_next_audit(client, app, monkeypatch, tmp_path):
    seen = _capture_chat(
        app, monkeypatch,
        "AUDIT bad vocab\nVOCAB_FLAG: consistent -> unbiased\n"
        "VOCAB_FLAG: convergence -> continuity")
    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "speech " * 100)
    f = make_webm(tmp_path / "a.webm", 271)
    client.post("/api/recordings",
                files={"file": ("a.webm", f.read_bytes(), "audio/webm")})
    from db import SessionLocal, VocabFlag
    s = SessionLocal()
    flags = s.query(VocabFlag).all()
    s.close()
    assert {(v.term_used, v.term_meant) for v in flags} == {
        ("consistent", "unbiased"), ("convergence", "continuity")}

    f2 = make_webm(tmp_path / "b.webm", 271)
    client.post("/api/recordings",
                files={"file": ("b.webm", f2.read_bytes(), "audio/webm")})
    second_audit_prompt = seen[-1]["user"]
    assert "Previously flagged vocabulary confusions" in second_audit_prompt
    assert "'consistent' used for 'unbiased'" in second_audit_prompt


# ---------- drift review ----------

def _seed_pass(client, app, monkeypatch, title):
    replies = iter(["Q?", "VERDICT: PASS — fine"])
    monkeypatch.setattr(app.llm, "_chat", lambda *a, **k: next(replies))
    tid = gated(client, title)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    return tid


def test_drift_review_flags_flips_in_export(client, app, monkeypatch):
    tid = _seed_pass(client, app, monkeypatch, "Derive OLS")
    seen = _capture_chat(app, monkeypatch, "VERDICT: FAIL — vague on re-read")
    out = client.post("/api/review/weekly").json()
    assert out["reviewed"] == [tid] and out["flips"] == [tid]
    assert "independent second grading" in seen[0]["user"]
    body = client.get("/api/export").text
    assert "Drift report" in body and "vague on re-read" in body
    # original verdict untouched — report only
    t = client.get("/api/tasks").json()["tasks"][0]
    assert t["status"] == "passed"


def test_drift_review_no_flip_no_report(client, app, monkeypatch):
    _seed_pass(client, app, monkeypatch, "Derive OLS")
    _capture_chat(app, monkeypatch, "VERDICT: PASS — still specific")
    assert client.post("/api/review/weekly").json()["flips"] == []
    assert "no drift detected" in client.get("/api/export").text


# ---------- the simulated week ----------

def test_simulated_week_export(client, app, monkeypatch, tmp_path):
    freeze(app, "2026-07-11")  # tasks below are backdated Jul 5-10; "today" must
    # actually be the 11th or llm_calls (timestamped from real now(), not the
    # task's date) land outside the ?from=&to= export window and vanish.
    n = {"i": 0}

    def week_chat(system, user, **kw):
        n["i"] += 1
        if "Student artifact" in user:
            return f"Q{n['i']}: justify the edge case?"
        if "Student answer" in user:
            return ("VERDICT: FAIL — hedged\nVOCAB_FLAG: consistent -> unbiased"
                    if n["i"] % 4 == 0 else "VERDICT: PASS — specific")
        return "AUDIT: 6 fillers/min is too high\nVOCAB_FLAG: parameter -> argument"
    monkeypatch.setattr(app.llm, "_chat", week_chat)
    monkeypatch.setattr(app.transcribe, "transcribe",
                        lambda p: "um so basically the proof " * 40)

    for day in range(5, 11):  # Jul 5–10, "today" is the 11th
        date = f"2026-07-{day:02d}"
        client.post("/api/tasks", json={"title": f"simple d{day}",
                                        "type": "simple", "date": date})
        tid = client.post("/api/tasks", json={
            "title": f"Derive SVD day {day}", "type": "gated",
            "date": date}).json()["id"]
        client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
        client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    f = make_webm(tmp_path / "week.webm", 271)
    rid = client.post("/api/recordings",
                      files={"file": ("w.webm", f.read_bytes(), "audio/webm")}).json()["id"]
    client.post(f"/api/recordings/{rid}/viewed")
    app._catch_up()                      # closes the neglected past days
    client.post("/api/day/close")
    client.post("/api/review/weekly")

    body = client.get("/api/export?from=2026-07-05&to=2026-07-11").text
    for needle in ("## 2026-07-05", "[late]", "Vocabulary ledger",
                   "'parameter' used for 'argument'", "Evaluator audit trail",
                   "question_gen:", "answer_eval:", "transcript_audit:",
                   "wpm", "fillers/min", "Drift report"):
        assert needle in body, f"missing from export: {needle}"
    (tmp_path / "week_export.md").write_text(body)
