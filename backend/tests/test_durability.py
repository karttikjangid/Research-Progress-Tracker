"""Durability: crash recovery, idempotent close, catch-up, migrations, export."""
import sqlite3

from conftest import ARTIFACT, gated, make_webm


def _upload(client, tmp_path, seconds=271, name="ok.webm"):
    f = make_webm(tmp_path / name, seconds)
    return client.post("/api/recordings",
                       files={"file": (name, f.read_bytes(), "audio/webm")})


def _rec_status(client, rid):
    for day in client.get("/api/history").json():
        for r in day["recordings"]:
            if r["id"] == rid:
                return r["status"]
    return None


# ---------- recording pipeline resilience ----------

def test_transcription_crash_then_retry(client, mock_llm, tmp_path, app, monkeypatch):
    def boom(_):
        raise RuntimeError("simulated whisper OOM")
    monkeypatch.setattr(app.transcribe, "transcribe", boom)
    r = _upload(client, tmp_path)
    assert r.status_code == 500 and "retry" in r.json()["detail"]
    rid = client.get("/api/history").json()[0]["recordings"][0]["id"]
    assert _rec_status(client, rid) == "transcription_failed"

    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "um so basically svd")
    r2 = client.post(f"/api/recordings/{rid}/retry")
    assert r2.status_code == 200 and r2.json()["status"] == "done"
    assert client.post(f"/api/recordings/{rid}/viewed").status_code == 200


def test_kill9_orphan_uploaded_row_recovers_via_retry(client, mock_llm, tmp_path,
                                                      app, monkeypatch):
    """Simulates kill -9 after the row commit but before transcription ended:
    row exists with status=uploaded, no transcript/audit files."""
    audio = make_webm(tmp_path / "orphan.webm", 271)
    from db import Recording, SessionLocal
    s = SessionLocal()
    r = Recording(date="2026-07-11", duration_sec=271, audio_path=str(audio),
                  transcript_path=str(tmp_path / "orphan.transcript.txt"),
                  audit_path=str(tmp_path / "orphan.audit.md"), status="uploaded")
    s.add(r)
    s.commit()
    rid = r.id
    s.close()
    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "recovered speech")
    out = client.post(f"/api/recordings/{rid}/retry")
    assert out.status_code == 200 and out.json()["status"] == "done"
    assert (tmp_path / "orphan.transcript.txt").read_text() == "recovered speech"


def test_audit_failure_keeps_transcript_and_retries_audit_only(
        client, mock_llm, tmp_path, app, monkeypatch):
    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "the transcript")
    calls = {"n": 0}

    def flaky_audit(_, **kw):
        calls["n"] += 1
        raise app.llm.LLMError("NIM down")
    monkeypatch.setattr(app.llm, "audit_transcript", flaky_audit)
    r = _upload(client, tmp_path)
    assert r.status_code == 503
    rid = client.get("/api/history").json()[0]["recordings"][0]["id"]
    assert _rec_status(client, rid) == "audit_failed"

    monkeypatch.setattr(app.transcribe, "transcribe",
                        lambda p: (_ for _ in ()).throw(AssertionError("must not re-transcribe")))
    monkeypatch.setattr(app.llm, "audit_transcript", lambda t, **kw: "AUDIT ok")
    out = client.post(f"/api/recordings/{rid}/retry")
    assert out.status_code == 200 and out.json()["audit"] == "AUDIT ok"


def test_retry_on_done_recording_409(client, mock_llm, tmp_path, app, monkeypatch):
    monkeypatch.setattr(app.transcribe, "transcribe", lambda p: "fine")
    rid = _upload(client, tmp_path).json()["id"]
    assert client.post(f"/api/recordings/{rid}/retry").status_code == 409


def test_rejected_upload_never_deletes_bytes(client, mock_llm, tmp_path, app):
    _upload(client, tmp_path, seconds=10, name="short.webm")
    audio_dir = app.infra.DATA_DIR / "audio"
    kept = list(audio_dir.rglob("*.rejected.webm"))
    assert len(kept) == 1 and kept[0].stat().st_size > 0


# ---------- day close ----------

def test_day_close_idempotent(client, app):
    tid = client.post("/api/tasks", json={"title": "t", "type": "simple"}).json()["id"]
    client.post(f"/api/tasks/{tid}/complete")
    r1 = client.post("/api/day/close").json()
    r2 = client.post("/api/day/close").json()
    assert not r1["already_closed"] and r2["already_closed"]
    lines = app.infra.PUBLIC_LOG.read_text().splitlines()
    assert len(lines) == 1  # one ping, not two

    # state changed -> a re-close pings the UPDATED line once
    t2 = client.post("/api/tasks", json={"title": "t2", "type": "simple"}).json()["id"]
    client.post(f"/api/tasks/{t2}/complete")
    r3 = client.post("/api/day/close").json()
    assert not r3["already_closed"]
    assert len(app.infra.PUBLIC_LOG.read_text().splitlines()) == 2


def test_day_close_writes_backup(client, app):
    client.post("/api/tasks", json={"title": "t", "type": "simple"})
    client.post("/api/day/close")
    backups = [d for d in app.infra.BACKUP_DIR.iterdir() if d.is_dir()]
    assert backups and (backups[0] / "gatekeeper.db").exists()


def test_catchup_closes_neglected_past_day(client, app):
    client.post("/api/tasks",
                json={"title": "old", "type": "simple", "date": "2026-07-01"})
    app._catch_up()
    from db import DayLog, SessionLocal
    s = SessionLocal()
    row = s.get(DayLog, "2026-07-01")
    s.close()
    assert row and row.late and "[late]" in row.summary_line
    assert "[late]" in app.infra.PUBLIC_LOG.read_text()
    app._catch_up()  # idempotent: no second row, no second ping
    assert app.infra.PUBLIC_LOG.read_text().count("[late]") == 1


# ---------- migrations / export ----------

def test_migrations_rebuild_schema_from_nothing(app):
    from db import DB_PATH
    n_migrations = len(list(app.infra.MIGRATIONS.glob("[0-9]*.sql")))
    v = sqlite3.connect(DB_PATH).execute(
        "SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert v == n_migrations >= 3
    cols = {r[1] for r in sqlite3.connect(DB_PATH).execute(
        "PRAGMA table_info(recordings)")}
    assert "status" in cols


def test_wal_mode_enabled(app):
    from db import engine
    from sqlalchemy import text
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_export_markdown(client, mock_llm, app):
    tid = client.post("/api/tasks", json={"title": "Derive SVD", "type": "gated"}).json()["id"]
    client.post(f"/api/tasks/{tid}/artifact", json={"artifact": ARTIFACT})
    client.post("/api/day/close")
    r = client.get("/api/export?from=2026-07-01")
    assert r.status_code == 200
    body = r.text
    assert "# Gatekeeper 2026-07-01" in body
    assert "- [open] (gated) Derive SVD" in body
    assert client.get("/api/export?from=notadate").status_code == 422
