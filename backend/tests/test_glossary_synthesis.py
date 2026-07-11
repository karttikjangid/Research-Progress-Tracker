"""Glossary (bulk paste, overload, search), evaluator injection for DECODE
tasks + transcript audits, and the weekly synthesis. LLM transport mocked."""
from conftest import ARTIFACT, gated, make_webm

TABLE = """\
| symbol | type | meaning | source |
|--------|------|---------|--------|
| \\sigma_i | scalar | i-th singular value | Golub SVD |
| \\Sigma | matrix | diagonal matrix of singular values | Golub SVD |
| only two cells |
| \\sigma_i | scalar | standard deviation | Stats notes |
"""


def _capture_chat(app, monkeypatch, reply):
    seen = []

    def fake_chat(system, user, **kw):
        seen.append({"system": system, "user": user})
        return reply(len(seen)) if callable(reply) else reply
    monkeypatch.setattr(app.llm, "_chat", fake_chat)
    return seen


# ---------- bulk paste + overload + dup + search ----------

def test_bulk_paste_accepts_valid_rejects_malformed(client, app):
    r = client.post("/api/glossary", json={"paste": TABLE}).json()
    added = {(g["symbol"], g["meaning"]) for g in r["added"]}
    assert ("\\sigma_i", "i-th singular value") in added
    assert ("\\Sigma", "diagonal matrix of singular values") in added
    assert len(r["added"]) == 3
    assert len(r["rejected"]) == 1
    assert "expected 4 columns" in r["rejected"][0]["reason"]


def test_overload_flags_both_rows(client, app):
    client.post("/api/glossary", json={"paste": TABLE})
    rows = client.get("/api/glossary?q=sigma_i").json()  # two meanings for one symbol
    assert len(rows) == 2 and all(g["is_overload"] for g in rows)
    # the non-overloaded symbol is untouched
    assert client.get("/api/glossary?q=Sigma").json()  # \Sigma present
    sig = [g for g in client.get("/api/glossary").json() if g["symbol"] == "\\Sigma"]
    assert sig and sig[0]["is_overload"] is False


def test_single_row_and_exact_duplicate_409(client, app):
    body = {"symbol": "\\lambda", "type_annotation": "scalar",
            "meaning": "eigenvalue", "source_paper": "Strang"}
    assert client.post("/api/glossary", json=body).status_code == 201
    assert client.post("/api/glossary", json=body).status_code == 409  # exact dup
    # same symbol, different source + meaning → accepted, overload
    r = client.post("/api/glossary", json={**body, "source_paper": "Other",
                                           "meaning": "regularization weight"})
    assert r.status_code == 201 and r.json()["is_overload"] is True


def test_search_matches_symbol_and_meaning(client, app):
    client.post("/api/glossary", json={"symbol": "\\rho", "meaning": "spectral radius",
                                       "source_paper": "P"})
    assert [g["symbol"] for g in client.get("/api/glossary?q=rho").json()] == ["\\rho"]
    assert [g["symbol"] for g in client.get("/api/glossary?q=spectral").json()] == ["\\rho"]
    assert client.get("/api/glossary?q=nonesuch").json() == []


def test_single_missing_meaning_422(client, app):
    assert client.post("/api/glossary", json={"symbol": "\\x"}).status_code == 422


# ---------- evaluator injection: DECODE question_gen ----------

def test_decode_task_injects_recent_glossary(client, app, monkeypatch):
    client.post("/api/glossary", json={"symbol": "\\sigma_i", "type_annotation": "scalar",
                                       "meaning": "i-th singular value", "source_paper": "Golub"})
    seen = _capture_chat(app, monkeypatch, "A probing question?")
    tid = gated(client, "DECODE the SVD existence proof")
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    prompt = seen[-1]["user"]
    assert "do not re-ask their definitions; build a question on top of them" in prompt
    assert "i-th singular value" in prompt


def test_recall_decode_task_also_injects(client, app, monkeypatch):
    client.post("/api/glossary", json={"symbol": "\\Sigma", "meaning": "singular value matrix",
                                       "source_paper": "Golub"})
    seen = _capture_chat(app, monkeypatch, "Q?")
    tid = gated(client, "RECALL: DECODE the SVD existence proof")
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    assert "singular value matrix" in seen[-1]["user"]


def test_non_decode_task_gets_no_glossary(client, app, monkeypatch):
    client.post("/api/glossary", json={"symbol": "\\sigma_i", "meaning": "i-th singular value",
                                       "source_paper": "Golub"})
    seen = _capture_chat(app, monkeypatch, "Q?")
    tid = gated(client, "Prove OLS is BLUE")
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    assert "do not re-ask" not in seen[-1]["user"]
    assert "i-th singular value" not in seen[-1]["user"]


# ---------- evaluator injection: transcript audit matching ----------

def test_transcript_audit_injects_matching_glossary(client, app, monkeypatch, tmp_path):
    client.post("/api/glossary", json={"symbol": "eigenvalue", "type_annotation": "scalar",
                                       "meaning": "characteristic root", "source_paper": "Strang"})
    client.post("/api/glossary", json={"symbol": "\\notintranscript",
                                       "meaning": "never spoken", "source_paper": "X"})
    seen = _capture_chat(app, monkeypatch, "AUDIT: fine")
    monkeypatch.setattr(app.transcribe, "transcribe",
                        lambda p: "today I discuss the eigenvalue and why it matters " * 20)
    f = make_webm(tmp_path / "g.webm", 271)
    client.post("/api/recordings", files={"file": ("g.webm", f.read_bytes(), "audio/webm")})
    prompt = seen[-1]["user"]
    assert "Decoded glossary terms appearing in this transcript" in prompt
    assert "eigenvalue" in prompt
    assert "\\notintranscript" not in prompt  # only matched terms are injected


# ---------- weekly synthesis ----------

def _seed_pass(client, app, monkeypatch, title="Derive SVD"):
    replies = iter(["Q?", "VERDICT: PASS — specific and correct"])
    monkeypatch.setattr(app.llm, "_chat", lambda *a, **k: next(replies))
    tid = gated(client, title)
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    from conftest import ANSWER
    client.post(f"/api/tasks/{tid}/answer", json={"answer": ANSWER})
    return tid


def _weekly_chat(app, monkeypatch, synthesis):
    """weekly_review makes TWO kinds of LLM call: the drift re-grade (needs a
    valid VERDICT) and the synthesis (free text). Route by prompt."""
    def chat(system, user, **kw):
        return synthesis if "This week's raw log" in user else "VERDICT: PASS — still specific"
    monkeypatch.setattr(app.llm, "_chat", chat)


def test_weekly_synthesis_persists_and_appends_to_export(client, app, monkeypatch):
    _seed_pass(client, app, monkeypatch)
    _weekly_chat(app, monkeypatch, "SYNTHESIS: 3 weakest points with quoted rows")
    out = client.post("/api/review/weekly").json()
    assert out["synthesis_week_start"]
    from db import SessionLocal, Synthesis
    s = SessionLocal()
    rows = s.query(Synthesis).all()
    s.close()
    assert len(rows) == 1 and "3 weakest points" in rows[0].content
    body = client.get("/api/export").text
    assert "## Weekly synthesis" in body and "3 weakest points" in body


def test_weekly_synthesis_upserts_on_rerun(client, app, monkeypatch):
    _seed_pass(client, app, monkeypatch)
    _weekly_chat(app, monkeypatch, "SYNTHESIS v1")
    client.post("/api/review/weekly")
    _weekly_chat(app, monkeypatch, "SYNTHESIS v2")
    client.post("/api/review/weekly")
    from db import SessionLocal, Synthesis
    s = SessionLocal()
    rows = s.query(Synthesis).all()
    s.close()
    assert len(rows) == 1 and rows[0].content == "SYNTHESIS v2"  # same week PK, refreshed


def test_synthesis_assembly_graceful_when_optional_table_missing(client, app, monkeypatch):
    _seed_pass(client, app, monkeypatch)
    # simulate a build without the optional sessions + tastelog tables
    from sqlalchemy import text
    from db import engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE sessions"))
        conn.execute(text("DROP TABLE tastelog"))
    _weekly_chat(app, monkeypatch, "SYNTHESIS despite missing tables")
    out = client.post("/api/review/weekly")
    assert out.status_code == 200 and out.json()["synthesis_week_start"]
    from db import SessionLocal, Synthesis
    s = SessionLocal()
    n = s.query(Synthesis).count()
    s.close()
    assert n == 1
