"""Gatekeeper backend — single FastAPI process, localhost only.

Enforcement lives in db.py (state machine, immutability, limits); routes
pre-check only to give clear errors before spending an LLM call, and map
GamingError → 409, GatedLimitExceeded → 400, LLMError → 503 (fail closed).
"""
import base64
import datetime as dt
import hmac
import json
import os
import random
import re
from contextlib import asynccontextmanager
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fsrs import Card, Rating, Scheduler
from pydantic import BaseModel, field_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError

load_dotenv()  # before local imports that read env at call time

import clock  # noqa: E402
import infra  # noqa: E402
import llm  # noqa: E402
import transcribe  # noqa: E402
from db import (ARMS, DATA_DIR, DB_PATH, MAX_REVIEWS,  # noqa: E402
                RECALL_PREFIX, SESSION_KINDS, SESSION_MAX_HOURS, Answer, DayLog,
                AppSetting, DriftReport, GamingError, GatedLimitExceeded,
                Glossary, HabitLog, LLMCall, Recording, Review, RoadmapTicket,
                SessionLocal, Synthesis, Task, TasteLog, VocabFlag, WorkSession)

ROOT = Path(__file__).resolve().parent.parent
MIN_RECORDING_SEC = 270  # 4:30
MIN_ARTIFACT_CHARS = 200
MIN_ANSWER_CHARS = 100
MAX_ANSWER_OVERLAP = 0.70
MAX_OVERDUE_STREAK_DAYS = 2  # a review overdue by MORE than this breaks a streak-day

# Day-scale FSRS: no sub-day learning/relearning steps and no fuzzing, so every
# self-grade maps to a clean, deterministic next-due date (Again/Hard → +1d,
# Good → +2d, then intervals grow with stability). See decisions.md.
_SCHEDULER = Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False)
_GRADE_TO_RATING = {"recalled": Rating.Good, "partial": Rating.Hard,
                    "forgot": Rating.Again}


def _now() -> dt.datetime:
    return clock.now_utc()  # tz-aware UTC — the one 'now' (H2)


def _advance_card(state_json: str, grade: str, when: dt.datetime) -> Card:
    """Feed the stored card + grade to FSRS; return the rescheduled card."""
    card = Card.from_dict(json.loads(state_json))
    card, _log = _SCHEDULER.review_card(card, _GRADE_TO_RATING[grade],
                                        review_datetime=when)
    return card


@asynccontextmanager
async def _lifespan(_app):
    _daily_maintenance()
    yield


app = FastAPI(title="Gatekeeper", lifespan=_lifespan)


# Optional single-shared-password gate for private hosting. When
# GATEKEEPER_PASSWORD is set, every request (app + API) requires HTTP Basic auth
# with that password (any username). Unset (local dev) → no auth. The browser's
# native credential prompt means no login UI is needed.
@app.middleware("http")
async def _require_password(request: Request, call_next):
    pw = os.getenv("GATEKEEPER_PASSWORD")
    if pw and request.url.path != "/healthz":
        supplied, header = None, request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode("utf-8").partition(":")[2]
            except Exception:
                supplied = None
        if supplied is None or not hmac.compare_digest(supplied, pw):
            return Response("Authentication required", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Sentinel"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    """Unauthenticated liveness probe for the host's health check."""
    return {"ok": True}


def _daily_maintenance():
    """First-startup-of-the-day backup + catch-up close of neglected days."""
    _close_orphan_sessions()  # any session still open across a restart is dead
    if not (infra.BACKUP_DIR / today()).exists():
        infra.backup(DB_PATH, today())
    _catch_up()


def _catch_up():
    s = SessionLocal()
    try:
        dates = ({d for (d,) in s.query(Task.date)
                  .filter(Task.type != "reflection")}
                 | {d for (d,) in s.query(Recording.date)})
        for date in sorted(dates):
            if date < today() and not s.get(DayLog, date):
                sv = _streak_values(s, date, _timer_honored(s, date))
                line = _close_line(s, date, sv) + " [late]"
                pinged = _ping(line)
                s.add(DayLog(date=date, summary_line=line, pinged=pinged, late=True,
                             streak_day=sv["streak_day"], grace_used=sv["grace_used"],
                             current_streak=sv["current_streak"],
                             longest_streak=sv["longest_streak"]))
                s.commit()
                infra.log.info("catch-up close for %s: %s", date, line)
    except Exception:
        infra.log.exception("catch-up failed")  # never block startup
    finally:
        s.close()


@app.exception_handler(GatedLimitExceeded)
async def _limit_handler(_req, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(GamingError)
async def _gaming_handler(_req, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def _validation_handler(_req, exc):
    msg = "; ".join(str(e.get("msg", "invalid input")) for e in exc.errors())
    return JSONResponse(status_code=422, content={"detail": msg})


@app.exception_handler(Exception)
async def _unhandled_handler(_req, exc):
    infra.log.error("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500,
                        content={"detail": "internal error — see logs/gatekeeper.log"})


def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def today() -> str:
    return clock.today_local()  # IST calendar date (H2), not host-TZ dependent


# ---------- tasks ----------

class TaskCreate(BaseModel):
    title: str
    type: str
    date: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        if not v.strip():
            raise ValueError("title required")
        return v.strip()

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in ("simple", "gated"):
            raise ValueError("type must be 'simple' or 'gated'")
        return v


@app.get("/api/tasks")
def list_tasks(date: str | None = None, s=Depends(db)):
    date = date or today()
    tasks = (s.query(Task).filter(Task.date == date, Task.type != "reflection")
             .order_by(Task.id).all())
    rec = (s.query(Recording).filter(Recording.date == date)
           .order_by(Recording.id.desc()).first())
    # had_session_today mirrors _close_line's `has_sessions`: the day-close
    # TASTELOG-MISSING flag only fires when the day had ≥1 work session, so the
    # close modal must know this to warn on exactly the same rule (not a stricter
    # or looser one).
    had_session = s.query(WorkSession).filter(WorkSession.date == date).count() > 0
    return {"date": date,
            "tasks": [t.as_dict() for t in tasks],
            "reviews_due": _reviews_due_count(s, date),
            "had_session_today": had_session,
            "verbal": {"recorded": rec is not None,
                       "done": bool(rec and rec.audit_viewed),
                       "recording_id": rec.id if rec else None}}


@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreate, s=Depends(db)):
    t = Task(date=body.date or today(), title=body.title, type=body.type)
    s.add(t)
    s.commit()  # before_flush enforces the gated-per-day cap
    return t.as_dict()


@app.post("/api/tasks/{task_id}/complete")
def complete_simple(task_id: int, s=Depends(db)):
    t = s.get(Task, task_id)
    if not t:
        raise HTTPException(404, "no such task")
    if t.status == "done":
        raise HTTPException(409, "already done")
    t.status = "done"  # db layer 409s any illegal transition (e.g. gated tasks)
    s.commit()
    return t.as_dict()


# ---------- gated flow ----------

class ArtifactIn(BaseModel):
    artifact: str

    @field_validator("artifact")
    @classmethod
    def _min(cls, v):
        v = v.strip()
        if len(v) < MIN_ARTIFACT_CHARS:
            raise ValueError(f"artifact must be ≥{MIN_ARTIFACT_CHARS} chars of "
                             "actual work — not a topic name")
        return v


class AnswerIn(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def _min(cls, v):
        v = v.strip()
        if len(v) < MIN_ANSWER_CHARS:
            raise ValueError(f"answer must be ≥{MIN_ANSWER_CHARS} chars — commit "
                             "to a real claim")
        return v


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _gated_task(s, task_id: int) -> Task:
    """Fetch + fast pre-checks so gaming attempts don't burn an LLM call.
    The db layer independently enforces all of this at commit time."""
    t = s.get(Task, task_id)
    if not t:
        raise HTTPException(404, "no such task")
    if t.type != "gated":
        raise HTTPException(409, "not a gated task")
    if t.status == "passed":
        raise HTTPException(409, "already passed")
    if t.status == "failed_final":
        raise HTTPException(409, "failed twice today — locked until tomorrow")
    return t


_STOP = {"the", "and", "for", "from", "with", "this", "that", "day"}


def _title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", title.lower())} - _STOP


def _similar_questions(s, t: Task) -> list[str]:
    """Last 5 questions asked for tasks with title-token overlap (naive)."""
    words = _title_tokens(t.title)
    out = []
    for other in (s.query(Task).filter(Task.id != t.id, Task.question != "",
                                       Task.type != "reflection")
                  .order_by(Task.id.desc()).limit(100)):
        if words & _title_tokens(other.title):
            out.append(other.question)
            if len(out) == 5:
                break
    return out


@app.post("/api/tasks/{task_id}/artifact")
def submit_artifact(task_id: int, body: ArtifactIn, s=Depends(db)):
    t = _gated_task(s, task_id)
    if t.question and not t.answer:
        raise HTTPException(409, "a question is already pending — answer it first")
    weakness = t.reason if t.verdict == "FAIL" else None  # harder retry target
    glossary = _glossary_lines(_glossary_recent(s, 15)) if _is_decode(t.title) else None
    try:
        question = llm.generate_question(body.artifact, task_id=t.id,
                                         avoid=_similar_questions(s, t),
                                         weakness=weakness, glossary=glossary)
    except llm.LLMError as e:
        raise HTTPException(503, str(e))
    # Compare-and-set: only ONE concurrent artifact submission can win the
    # "open a fresh question" transition. A task is eligible iff it has no
    # pending question (question='') OR its prior attempt was answered
    # (answer!=''), and it is not closed. The WHERE predicate is evaluated
    # atomically under SQLite's write lock, so a racing second submission
    # matches 0 rows (or hits BUSY_SNAPSHOT) → 409, never a double question.
    pending = "a question is already pending — answer it first"
    try:
        res = s.execute(
            update(Task)
            .where(Task.id == t.id,
                   Task.status.in_(("open", "failed_once")),
                   (Task.question == "") | (Task.answer != ""))
            .values(artifact=body.artifact, question=question, answer="",
                    verdict="", reason="")
            .execution_options(synchronize_session=False))
        if res.rowcount == 0:
            s.rollback()
            raise HTTPException(409, pending)
        s.commit()
    except (IntegrityError, OperationalError):
        s.rollback()
        raise HTTPException(409, pending)
    return {"question": question, "attempt": t.attempts + 1}


@app.post("/api/tasks/{task_id}/answer")
def submit_answer(task_id: int, body: AnswerIn, s=Depends(db)):
    t = _gated_task(s, task_id)
    if not t.question:
        raise HTTPException(409, "no pending question — submit an artifact first")
    if t.answer:
        raise HTTPException(409, "a submitted answer can never be modified")
    art, ans = _tokens(t.artifact), _tokens(body.answer)
    if ans and len(art & ans) / len(ans) > MAX_ANSWER_OVERLAP:
        raise HTTPException(422, "answer is mostly copied from the artifact — "
                                 "answer the question in your own words")
    try:
        verdict, reason = llm.evaluate_answer(t.artifact, t.question, body.answer,
                                              task_id=t.id)
    except llm.LLMError as e:
        raise HTTPException(503, str(e))  # fail closed: task untouched
    immutable = "a submitted answer can never be modified"
    t.answer, t.verdict, t.reason = body.answer, verdict, reason
    t.attempts += 1
    # Append-only ledger row: UNIQUE(task_id, attempt_no) is the DB-level atomic
    # guard against a concurrent duplicate submission. Flush it NOW (before any
    # side effect) so a racing duplicate is rejected here; a successful flush
    # also holds the write lock through commit, so nothing can interleave.
    s.add(Answer(task_id=t.id, attempt_no=t.attempts, answer_text=body.answer,
                 created_at=_now().isoformat(timespec="seconds")))
    try:
        s.flush()
    except (IntegrityError, OperationalError):
        s.rollback()  # lost the race for this attempt slot; task untouched by us
        raise HTTPException(409, immutable)
    if verdict == "PASS":
        t.status = "passed"
        _seed_review(s, t)  # first spaced-repetition review, as a new FSRS card
    else:
        t.status = "failed_once" if t.attempts == 1 else "failed_final"
    try:
        s.commit()
    except (IntegrityError, OperationalError):
        s.rollback()
        raise HTTPException(409, immutable)
    out = t.as_dict()
    out["retry_available"] = t.status == "failed_once"
    return out


# ---------- spaced repetition (FSRS, self-graded) ----------

def _seed_review(s, task: Task):
    """A newly-passed gated task enters review as a brand-new FSRS card, due
    today. Idempotent guard: a task is passed at most once, but never seed twice."""
    if s.query(Review).filter(Review.source_task_id == task.id).count():
        return
    s.add(Review(source_task_id=task.id, due_date=today(),
                 fsrs_card_state=json.dumps(Card().to_dict()), status="due"))


def _reviews_due_count(s, date: str) -> int:
    return (s.query(Review)
            .filter(Review.status == "due", Review.due_date <= date).count())


class GradeIn(BaseModel):
    grade: str

    @field_validator("grade")
    @classmethod
    def _grade(cls, v):
        if v not in ("recalled", "partial", "forgot"):
            raise ValueError("grade must be recalled | partial | forgot")
        return v


@app.get("/api/reviews/due")
def reviews_due(date: str | None = None, s=Depends(db)):
    """Retrieval prompts only: the title, never the artifact/Q&A (that is the
    whole point — you must recall it before revealing). Overdue rolls forward."""
    date = date or today()
    rows = (s.query(Review).filter(Review.status == "due", Review.due_date <= date)
            .order_by(Review.due_date, Review.id).all())
    ids = {r.source_task_id for r in rows}
    titles = ({t.id: t.title for t in s.query(Task).filter(Task.id.in_(ids))}
              if ids else {})
    return [{"id": r.id, "source_task_id": r.source_task_id,
             "title": titles.get(r.source_task_id, "(task removed)"),
             "due_date": r.due_date, "overdue": r.due_date < date} for r in rows]


@app.post("/api/reviews/{rev_id}/reveal")
def reveal_review(rev_id: int, s=Depends(db)):
    r = s.get(Review, rev_id)
    if not r:
        raise HTTPException(404, "no such review")
    if not r.revealed_at:
        r.revealed_at = _now().isoformat(timespec="seconds")
        s.commit()
    src = s.get(Task, r.source_task_id)
    return {"id": r.id, "revealed_at": r.revealed_at,
            "artifact": src.artifact if src else "",
            "question": src.question if src else "",
            "answer": src.answer if src else "",
            "verdict": src.verdict if src else "",
            "reason": src.reason if src else ""}


@app.post("/api/reviews/{rev_id}/grade")
def grade_review(rev_id: int, body: GradeIn, s=Depends(db)):
    r = s.get(Review, rev_id)
    if not r:
        raise HTTPException(404, "no such review")
    if r.grade:
        raise HTTPException(409, "a submitted grade can never be modified")
    if not r.revealed_at:
        raise HTTPException(409, "reveal the original before grading")
    card = _advance_card(r.fsrs_card_state, body.grade, _now())
    graded_at = _now().isoformat(timespec="seconds")
    regrade = "a submitted grade can never be modified"
    # Compare-and-set: only the transaction whose UPDATE still sees grade='' wins.
    # A racing second /grade matches 0 rows (or hits BUSY_SNAPSHOT) → 409, so the
    # chained review and RECALL gate below are created at most once.
    try:
        res = s.execute(
            update(Review)
            .where(Review.id == rev_id, Review.grade == "", Review.revealed_at != "")
            .values(grade=body.grade, graded_at=graded_at, status="done")
            .execution_options(synchronize_session=False))
        if res.rowcount == 0:
            s.rollback()
            raise HTTPException(409, regrade)
        # winner only — chain the next review until MAX_REVIEWS, spawn RECALL on 'forgot'
        done_count = s.query(Review).filter(
            Review.source_task_id == r.source_task_id).count()
        retired = done_count >= MAX_REVIEWS
        if not retired:
            s.add(Review(source_task_id=r.source_task_id,
                         due_date=clock.local_date_of(card.due),  # local date, not UTC (H2)
                         fsrs_card_state=json.dumps(card.to_dict()), status="due"))
        recall_task = None
        if body.grade == "forgot":  # self-graded failure → fresh LLM gate
            src = s.get(Task, r.source_task_id)
            base = src.title if src else f"review {r.id}"
            recall_task = Task(date=today(), title=f"{RECALL_PREFIX}{base}", type="gated")
            s.add(recall_task)
        s.commit()
    except (IntegrityError, OperationalError):
        s.rollback()
        raise HTTPException(409, regrade)
    r.grade, r.graded_at, r.status = body.grade, graded_at, "done"  # reflect the win
    return {**r.as_dict(), "retired": retired,
            "next_due": None if retired else clock.local_date_of(card.due),
            "recall_task_id": recall_task.id if recall_task else None}


# ---------- recordings ----------
# Durability order: audio fsynced to disk FIRST, row committed as 'uploaded'
# BEFORE transcription. A crash at any later point leaves a row that
# POST /api/recordings/{id}/retry can finish. No code path deletes a recording.

def _recording_dict(r: Recording) -> dict:
    """Recording row -> API shape, shared by /api/history and GET
    /api/recordings/{id}. audit_text is durable (DB column, populated by
    _process below) for any row processed after migration 017; the on-disk
    .audit.md file is only a fallback for older rows."""
    d = r.as_dict()
    d["transcript"] = r.transcript_text
    d["audit"] = r.audit_text
    if not d["audit"]:
        try:
            d["audit"] = Path(r.audit_path).read_text()
        except OSError:
            d["audit"] = "(audit file missing)"
    return d


def _write_local(path: Path, text: str, rec_id: int, kind: str) -> None:
    """Best-effort local convenience copy — NEVER the durability boundary. Must
    be called AFTER the DB column is already committed, and must never raise:
    Render's free tier wipes everything under DATA_DIR that Litestream doesn't
    replicate (it only replicates the SQLite file) on every restart, so the day
    directory a recording was uploaded into can simply be gone by the time a
    retry runs. Recording 3's audit_failed loop (2026-08-15) was exactly this
    bug the WRONG way around: an unguarded write_text() to a since-vanished
    directory crashed the request and threw away an already-completed,
    expensive LLM result that had never made it to the DB yet."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    except OSError as e:
        infra.log.warning("recording %s: local %s file not written (%s) — "
                          "harmless, the DB column is the durable copy",
                          rec_id, kind, e)


def _process(r: Recording, s) -> dict:
    """Transcribe + audit whatever is still missing, then mark done.

    r.transcript_text/r.audit_text (SQLite columns, replicated to Supabase by
    Litestream) are the durability boundary and the source of truth for what's
    already done — NOT the .txt/.md files under DATA_DIR, which live only on
    the current container's local disk and do not survive a restart on
    Render's ephemeral free tier. Each DB column is written and committed
    immediately after its step succeeds (not batched at the end) so a restart
    between steps can't silently lose already-completed work: a later retry
    picks up from whichever text columns are already populated. The on-disk
    .txt/.md files are still written as a local convenience but nothing here
    depends on them existing — which means the DB write must happen BEFORE the
    local write, not after (see _write_local's docstring for the incident that
    happens when this order is reversed).
    """
    tp, ap = Path(r.transcript_path), Path(r.audit_path)
    if not r.transcript_text:
        try:
            text = transcribe.transcribe(r.audio_path)
        except Exception:
            r.status = "transcription_failed"
            s.commit()
            infra.log.exception("recording %s: transcription failed", r.id)
            raise HTTPException(500, "transcription failed — "
                                f"POST /api/recordings/{r.id}/retry to re-run",
                                headers={"X-Recording-Id": str(r.id)})
        if not text:
            r.status = "transcription_failed"
            s.commit()
            raise HTTPException(400, "transcript came back empty — no speech "
                                f"detected; retry with /api/recordings/{r.id}/retry",
                                headers={"X-Recording-Id": str(r.id)})
        r.transcript_text = text
        s.commit()
        _write_local(tp, text, r.id, "transcript")
    if not r.audit_text:
        if r.wpm is None:  # deterministic stats before the LLM, survive retries
            st = transcribe.compute_stats(r.transcript_text, r.duration_sec)
            r.wpm, r.fillers_per_min = st["wpm"], st["fillers_per_min"]
            r.unique_ratio = st["unique_ratio"]
            r.longest_silence_sec = st["longest_silence_sec"]
            s.commit()
        stats = {"words_per_min": r.wpm, "fillers_per_min": r.fillers_per_min,
                 "unique_word_ratio": r.unique_ratio,
                 "longest_silence_sec": r.longest_silence_sec}
        ledger = [f"'{v.term_used}' used for '{v.term_meant}' ({v.date})"
                  for v in s.query(VocabFlag).order_by(VocabFlag.id.desc()).limit(20)]
        glossary = _glossary_lines(_glossary_matches(s, r.transcript_text, 10))
        try:
            audit = llm.audit_transcript(r.transcript_text, stats=stats, ledger=ledger,
                                         glossary=glossary)
        except llm.LLMError as e:
            r.status = "audit_failed"
            s.commit()
            infra.log.error("recording %s: audit failed: %s", r.id, e)
            raise HTTPException(503, f"{e} — POST /api/recordings/{r.id}/retry",
                                headers={"X-Recording-Id": str(r.id)})
        r.audit_text = audit
        s.commit()
        _write_local(ap, audit, r.id, "audit")
    r.status = "done"
    s.commit()
    return _recording_dict(r)


@app.post("/api/recordings", status_code=201)
def upload_recording(file: UploadFile, s=Depends(db)):
    date = today()
    day_dir = DATA_DIR / "audio" / date
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = clock.to_local(_now()).strftime("%H%M%S")
    audio_path = day_dir / f"{stamp}.webm"
    with open(audio_path, "wb") as f:
        f.write(file.file.read())
        f.flush()
        os.fsync(f.fileno())

    try:
        duration = transcribe.probe_duration(str(audio_path))
    except Exception:
        audio_path.rename(audio_path.with_suffix(".rejected.webm"))
        raise HTTPException(400, "could not decode audio — is this a real recording?")
    if duration < MIN_RECORDING_SEC:
        audio_path.rename(audio_path.with_suffix(".rejected.webm"))
        raise HTTPException(400, f"recording is {duration:.0f}s — minimum is 4:30. Rejected.")

    r = Recording(date=date, duration_sec=int(duration), audio_path=str(audio_path),
                  transcript_path=str(day_dir / f"{stamp}.transcript.txt"),
                  audit_path=str(day_dir / f"{stamp}.audit.md"), status="uploaded")
    s.add(r)
    s.commit()
    infra.log.info("recording %s uploaded: %ss at %s", r.id, int(duration), audio_path)
    return _process(r, s)


@app.get("/api/recordings/{rec_id}")
def get_recording(rec_id: int, s=Depends(db)):
    """Point lookup by id — lets a client that already knows the id (e.g. from
    the X-Recording-Id header on a failed upload/retry) recover a single
    recording without refetching all of /api/history."""
    r = s.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "no such recording")
    return _recording_dict(r)


@app.post("/api/recordings/{rec_id}/retry")
def retry_recording(rec_id: int, s=Depends(db)):
    r = s.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "no such recording")
    if r.status == "done":
        raise HTTPException(409, "already fully processed")
    infra.log.info("recording %s: retry requested from status %s", r.id, r.status)
    return _process(r, s)


@app.post("/api/recordings/{rec_id}/viewed")
def mark_viewed(rec_id: int, s=Depends(db)):
    r = s.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "no such recording")
    r.audit_viewed = True  # db layer 409s if audit_text isn't populated yet
    s.commit()
    return r.as_dict()


# ---------- leniency drift review ----------

@app.post("/api/review/weekly")
def weekly_review(s=Depends(db)):
    """Re-grade a random 3 of the week's PASSes, independently and harshly.
    Flips are reported (export markdown), never auto-refailed."""
    since = (dt.date.fromisoformat(today()) - dt.timedelta(days=7)).isoformat()
    passes = s.query(Task).filter(Task.verdict == "PASS",
                                  Task.date >= since).all()
    sample = random.sample(passes, min(3, len(passes)))
    flips = []
    for t in sample:
        try:
            v, reason = llm.evaluate_answer(t.artifact, t.question, t.answer,
                                            task_id=t.id, recheck=True)
        except llm.LLMError as e:
            raise HTTPException(503, str(e))
        if v == "FAIL":
            s.add(DriftReport(date=today(), task_id=t.id,
                              original_reason=t.reason,
                              new_verdict=v, new_reason=reason))
            flips.append(t.id)
            infra.log.error("DRIFT: task %s PASS flipped to FAIL on recheck", t.id)
    s.commit()  # drift persisted before synthesis, which may fail independently

    # Weekly synthesis over the ISO week's assembled log (graceful if optional
    # tables are absent). Upsert so a re-run in the same week refreshes it.
    _t = dt.date.fromisoformat(today())
    week_start = (_t - dt.timedelta(days=_t.weekday())).isoformat()
    markdown = _export_markdown(s, week_start, today())
    try:
        content = llm.weekly_synthesis(markdown)
    except llm.LLMError as e:
        raise HTTPException(503, str(e))
    s.merge(Synthesis(week_start=week_start, content=content,
                      created_at=_now().isoformat(timespec="seconds")))
    s.commit()
    return {"reviewed": [t.id for t in sample], "flips": flips,
            "synthesis_week_start": week_start}


# ---------- work sessions ----------
# Time is measured server-side from started_at → _now(); the client is never
# trusted for duration (same principle as recording length).

def _end_session(sess: WorkSession, when: dt.datetime, aborted=False, trigger=""):
    sess.ended_at = when.isoformat(timespec="seconds")
    sess.actual_minutes = round(
        (when - dt.datetime.fromisoformat(sess.started_at)).total_seconds() / 60, 2)
    sess.aborted = aborted
    if trigger:
        sess.abort_trigger = trigger


def _sweep_open_sessions(s, close_all: bool):
    """Auto-abort open sessions: every one at startup (close_all), or any that
    has outlived SESSION_MAX_HOURS during a run."""
    now = _now()
    for sess in s.query(WorkSession).filter(WorkSession.ended_at == ""):
        age_h = (now - dt.datetime.fromisoformat(sess.started_at)).total_seconds() / 3600
        if close_all or age_h > SESSION_MAX_HOURS:
            _end_session(sess, now, aborted=True, trigger="auto_close")
            infra.log.info("session %s auto-closed (age %.1fh)", sess.id, age_h)
    s.commit()


def _close_orphan_sessions():
    s = SessionLocal()
    try:
        _sweep_open_sessions(s, close_all=True)
    finally:
        s.close()


def _timer_honored(s, date: str) -> bool:
    """The one source of timer_honored: a completed (not auto-aborted)
    struggle_timer session that met its planned minutes. Wired into the streak
    and the day-close ping via day_log.timer_honored — not duplicated."""
    return s.query(WorkSession).filter(
        WorkSession.date == date, WorkSession.kind == "struggle_timer",
        WorkSession.aborted.is_(False), WorkSession.ended_at != "",
        WorkSession.actual_minutes >= WorkSession.planned_minutes).count() > 0


class SessionStart(BaseModel):
    kind: str
    planned_minutes: int
    notes: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in SESSION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(SESSION_KINDS)}")
        return v

    @field_validator("planned_minutes")
    @classmethod
    def _planned(cls, v):
        if v <= 0:
            raise ValueError("planned_minutes must be positive")
        return v


class SessionEnd(BaseModel):
    notes: str | None = None


@app.get("/api/sessions/current")
def current_session(s=Depends(db)):
    """Backend-authoritative truth for 'is a session actually running', so the
    frontend's localStorage cache (which only updates on a clean end_session
    call) can reconcile after a server restart, crash, or stale reload instead
    of showing a false lock. Sweeps >6h stragglers first so this is never
    itself stale. Supersedes the work-sessions session's 'no GET-sessions
    endpoint by design' — that call was about avoiding an unneeded surface,
    not a deliberate ban; a read-only reconciliation source is worth adding to
    fix a real false-lock bug per CLAUDE.md's authority to relax brittle
    locking. See SESSION_LOG.md."""
    _sweep_open_sessions(s, close_all=False)
    sess = s.query(WorkSession).filter(WorkSession.ended_at == "").first()
    return sess.as_dict() if sess else None


@app.post("/api/sessions/start", status_code=201)
def start_session(body: SessionStart, s=Depends(db)):
    _sweep_open_sessions(s, close_all=False)  # retire >6h stragglers before the check
    if s.query(WorkSession).filter(WorkSession.ended_at == "").count():
        raise HTTPException(409, "a session is already running — end it first")
    sess = WorkSession(date=today(), kind=body.kind, planned_minutes=body.planned_minutes,
                       started_at=_now().isoformat(timespec="seconds"),
                       notes=(body.notes or ""))
    s.add(sess)
    s.commit()
    return sess.as_dict()


@app.post("/api/sessions/{sid}/end")
def end_session(sid: int, body: SessionEnd | None = None, s=Depends(db)):
    sess = s.get(WorkSession, sid)
    if not sess:
        raise HTTPException(404, "no such session")
    if sess.ended_at:
        raise HTTPException(409, "session already ended")
    if body and body.notes:
        sess.notes = body.notes
    _end_session(sess, _now())
    s.commit()
    return sess.as_dict()


# ---------- tastelog (immutable end-of-day consolidation) ----------
# The end-of-day reflection: what you can explain now that you couldn't this
# morning (retrieval/consolidation), and the day's hardest sticking point. A
# non-empty sticking point is scheduled as tomorrow's spaced-repetition review.

# Fixed retrieval cue shown when a sticking-point review comes due.
STICKING_POINT_Q = ("Yesterday this was your hardest sticking point. Can you "
                    "resolve or explain it now, in your own words? If not, it recurs.")


class TasteLogIn(BaseModel):
    understood: str
    sticking_point: str = ""
    date: str | None = None

    @field_validator("understood")
    @classmethod
    def _understood(cls, v):
        v = v.strip()
        if not 10 <= len(v) <= 500:
            raise ValueError("understood must be 10–500 chars")
        return v

    @field_validator("sticking_point")
    @classmethod
    def _sp(cls, v):
        v = (v or "").strip()
        if v and not 10 <= len(v) <= 500:
            raise ValueError("sticking_point, if given, must be 10–500 chars")
        return v


def _seed_sticking_point_review(s, date: str, text: str):
    """Turn the day's sticking point into tomorrow's retrieval. It anchors to an
    inert `reflection` task (invisible in the fan/ticks, exempt from the gated
    cap, never transitions) purely so the existing FSRS review machinery — due
    list, reveal, self-grade, chaining — surfaces and schedules it unchanged."""
    tomorrow = (dt.date.fromisoformat(date) + dt.timedelta(days=1)).isoformat()
    cue = text if len(text) <= 100 else text[:99] + "…"
    t = Task(date=date, title=f"STICKING POINT — {cue}", type="reflection")
    t.artifact = text
    t.question = STICKING_POINT_Q
    s.add(t)
    s.flush()  # need t.id for the review
    s.add(Review(source_task_id=t.id, due_date=tomorrow,
                 fsrs_card_state=json.dumps(Card().to_dict()), status="due"))


@app.post("/api/tastelog", status_code=201)
def create_tastelog(body: TasteLogIn, s=Depends(db)):
    date = body.date or today()
    if s.get(TasteLog, date):
        raise HTTPException(409, "tastelog for this date is already written — immutable")
    s.add(TasteLog(date=date, understood=body.understood,
                   sticking_point=body.sticking_point))
    if body.sticking_point:
        _seed_sticking_point_review(s, date, body.sticking_point)
    s.commit()
    return s.get(TasteLog, date).as_dict()


@app.get("/api/tastelog")
def get_tastelog(date: str | None = None, s=Depends(db)):
    tl = s.get(TasteLog, date or today())
    return tl.as_dict() if tl else None


@app.get("/api/tastelog/verdict")
def tastelog_verdict(from_: str | None = Query(None, alias="from"),
                     to: str | None = None, s=Depends(db)):
    """Raw evidence only — per-arm tallies, aborted count, minutes by kind.
    No scores, no weights, no recommendation: a human decides on Oct 15."""
    try:
        to = to or today()
        from_ = from_ or (dt.date.fromisoformat(to) - dt.timedelta(days=6)).isoformat()
        dt.date.fromisoformat(from_)
    except ValueError:
        raise HTTPException(422, "from/to must be YYYY-MM-DD")
    drift = {a: 0 for a in ARMS}
    dread = {a: 0 for a in ARMS}
    # Only the retired drift/dread experiment rows carry arm attributions; new
    # reflection rows leave them "" and are simply not counted here.
    for tl in s.query(TasteLog).filter(TasteLog.date >= from_, TasteLog.date <= to):
        if tl.drift_arm in drift:
            drift[tl.drift_arm] += 1
        if tl.dread_arm in dread:
            dread[tl.dread_arm] += 1
    minutes: dict[str, float] = {}
    aborted = 0
    for x in s.query(WorkSession).filter(WorkSession.date >= from_, WorkSession.date <= to):
        aborted += bool(x.aborted)
        minutes[x.kind] = round(minutes.get(x.kind, 0.0) + (x.actual_minutes or 0.0), 2)
    return {"from": from_, "to": to, "drift": drift, "dread": dread,
            "aborted_sessions": aborted, "actual_minutes_by_kind": minutes}


# ---------- glossary (decoded notation; overloads surfaced, not deduped) ----------

def _is_decode(title: str) -> bool:
    return title.startswith("DECODE") or title.startswith("RECALL: DECODE")


def _glossary_lines(rows) -> list[str]:
    return [f"{g.symbol} : {g.type_annotation or '?'} — {g.meaning}"
            f" [{g.source_paper or '—'}]" for g in rows]


def _glossary_recent(s, n=15):
    return list(reversed(s.query(Glossary).order_by(Glossary.id.desc()).limit(n).all()))


def _glossary_matches(s, transcript: str, n=10):
    low = transcript.lower()
    out = []
    for g in s.query(Glossary).order_by(Glossary.id.desc()):
        if g.symbol.lower() in low or (g.meaning and g.meaning.lower() in low):
            out.append(g)
            if len(out) == n:
                break
    return out


def _insert_glossary(s, symbol, type_annotation, meaning, source_paper):
    """Returns (row, error). Exact (symbol+source) dup → error; a differing
    meaning for an existing symbol flags is_overload on the whole symbol set."""
    symbol, meaning = symbol.strip(), (meaning or "").strip()
    type_annotation, source_paper = (type_annotation or "").strip(), (source_paper or "").strip()
    if not symbol or not meaning:
        return None, "symbol and meaning are required"
    if s.query(Glossary).filter(Glossary.symbol == symbol,
                                Glossary.source_paper == source_paper).first():
        return None, "duplicate (symbol+source_paper)"
    same = s.query(Glossary).filter(Glossary.symbol == symbol).all()
    overload = any(r.meaning != meaning for r in same)
    g = Glossary(symbol=symbol, type_annotation=type_annotation, meaning=meaning,
                 source_paper=source_paper, first_seen_date=today(), is_overload=overload)
    if overload:
        for r in same:
            r.is_overload = True
    s.add(g)
    return g, None


_SEP_RE = re.compile(r"^:?-{2,}:?$")


def _parse_glossary_table(paste: str):
    """Yield ('ok', symbol, type, meaning, source) or ('bad', raw, reason) for
    each markdown table row `| symbol | type | meaning | source |`. Non-table
    lines, the header, and separator rows are skipped silently."""
    for raw in paste.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and all(_SEP_RE.match(c) for c in cells if c != ""):
            continue  # |---|---| separator
        if cells and cells[0].lower() == "symbol":
            continue  # header row
        if len(cells) != 4:
            yield ("bad", line, f"expected 4 columns, got {len(cells)}")
            continue
        yield ("ok", *cells)


class GlossaryIn(BaseModel):
    symbol: str | None = None
    type_annotation: str | None = None
    meaning: str | None = None
    source_paper: str | None = None
    paste: str | None = None  # markdown table → bulk mode


@app.post("/api/glossary", status_code=201)
def add_glossary(body: GlossaryIn, s=Depends(db)):
    if body.paste:  # bulk mode: reject bad rows, accept the rest, report both
        added, rejected = [], []
        for parsed in _parse_glossary_table(body.paste):
            if parsed[0] == "bad":
                rejected.append({"row": parsed[1], "reason": parsed[2]})
                continue
            _, sym, typ, mean, src = parsed
            g, err = _insert_glossary(s, sym, typ, mean, src)
            if err:
                rejected.append({"row": " | ".join([sym, typ, mean, src]), "reason": err})
            else:
                s.flush()  # so a repeat symbol later in the paste sees this one
                added.append(g.as_dict())
        s.commit()
        return {"added": added, "rejected": rejected}
    g, err = _insert_glossary(s, body.symbol or "", body.type_annotation,
                              body.meaning, body.source_paper)
    if err == "duplicate (symbol+source_paper)":
        raise HTTPException(409, err)
    if err:
        raise HTTPException(422, err)
    s.commit()
    return g.as_dict()


@app.get("/api/glossary")
def search_glossary(q: str | None = None, s=Depends(db)):
    query = s.query(Glossary)
    if q:
        like = f"%{q}%"
        query = query.filter(Glossary.symbol.ilike(like) | Glossary.meaning.ilike(like))
    return [g.as_dict() for g in query.order_by(Glossary.id.desc())]


@app.get("/api/vocab")
def vocab_ledger(s=Depends(db)):
    """Cumulative vocabulary error profile. Grouped by (term_used, term_meant)
    with a repeat count so a recurring confusion outweighs a one-off. Count
    desc, then most-recent first among equal counts. Read-only — the flags are
    written only by llm._record() when the examiner emits a VOCAB_FLAG line."""
    groups: dict[tuple[str, str], dict] = {}
    for v in s.query(VocabFlag).order_by(VocabFlag.id).all():
        key = (v.term_used, v.term_meant)
        g = groups.get(key)
        if g is None:
            groups[key] = g = {"term_used": v.term_used, "term_meant": v.term_meant,
                               "count": 0, "last_date": v.date, "sources": set()}
        g["count"] += 1
        if v.date >= g["last_date"]:
            g["last_date"] = v.date
        g["sources"].add(v.source)
    out = [{"term_used": g["term_used"], "term_meant": g["term_meant"],
            "count": g["count"], "last_date": g["last_date"],
            "sources": sorted(g["sources"])} for g in groups.values()]
    out.sort(key=lambda g: (g["count"], g["last_date"]), reverse=True)
    return out


# ---------- day close / week / history ----------

def _summary(s, date: str) -> str:
    gated = s.query(Task).filter(Task.date == date, Task.type == "gated").all()
    simple = s.query(Task).filter(Task.date == date, Task.type == "simple").all()
    verbal = (s.query(Recording)
              .filter(Recording.date == date, Recording.audit_viewed).count() > 0)
    nice = dt.date.fromisoformat(date).strftime("%b %-d")
    parts = [f"{sum(t.status == 'passed' for t in gated)}/{len(gated)} gated passed"
             if gated else "no gated tasks",
             f"{sum(t.status == 'done' for t in simple)}/{len(simple)} simple done"
             if simple else "no simple tasks",
             "verbal done" if verbal else "verbal MISSED"]
    return f"{nice}: " + ", ".join(parts)


def _ping(line: str) -> bool:
    """Telegram if configured (10s), public_log.md otherwise. Never raises."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": line}, timeout=10)
            if r.status_code == 200:
                infra.log.info("telegram ping ok: %s", line)
                return True
            infra.log.error("telegram HTTP %s — falling back to public_log", r.status_code)
        except requests.RequestException:
            infra.log.exception("telegram unreachable — falling back to public_log")
    try:
        with open(infra.PUBLIC_LOG, "a") as f:
            f.write(line + "\n")
        infra.log.info("public_log ping: %s", line)
    except OSError:
        infra.log.exception("public_log write failed — summary only in day_log")
    return False


# ---------- quality streak (computed ONLY here, server-side, at day close) ----------

def _grace_used_this_week(s, date: str) -> bool:
    """Has a grace token already been spent on an earlier day of the SAME ISO week?"""
    iy, iw, _ = dt.date.fromisoformat(date).isocalendar()
    for row in (s.query(DayLog)
                .filter(DayLog.date < date, DayLog.grace_used.is_(True))):
        ry, rw, _ = dt.date.fromisoformat(row.date).isocalendar()
        if (ry, rw) == (iy, iw):
            return True
    return False


def _streak_values(s, date: str, timer_honored: bool) -> dict:
    """Pure function of (this day's tasks/reviews/timer) + PRIOR day_logs.
    A streak-day requires all three: timer honored, no gated task ended
    failed_final, and no review overdue by more than MAX_OVERDUE_STREAK_DAYS."""
    failed_final = s.query(Task).filter(
        Task.date == date, Task.status == "failed_final").count() > 0
    cutoff = (dt.date.fromisoformat(date)
              - dt.timedelta(days=MAX_OVERDUE_STREAK_DAYS)).isoformat()
    # Deliberate: sticking-point reviews (source task type "reflection") count
    # here too — ignoring a logged sticking point breaks the streak exactly like
    # a lapsed passed-task review, to enforce follow-through on retrieval.
    overdue = s.query(Review).filter(
        Review.status == "due", Review.due_date < cutoff).count() > 0
    streak_day = bool(timer_honored) and not failed_final and not overdue

    prev = (s.query(DayLog).filter(DayLog.date < date)
            .order_by(DayLog.date.desc()).first())
    prev_current = prev.current_streak if prev else 0
    prev_longest = prev.longest_streak if prev else 0

    grace_used = False
    if streak_day:
        current = prev_current + 1
    elif not _grace_used_this_week(s, date):
        grace_used = True          # first miss this ISO week: streak survives
        current = prev_current
    else:
        current = 0                # second miss this week: streak breaks
    return {"streak_day": streak_day, "grace_used": grace_used,
            "current_streak": current,
            "longest_streak": max(prev_longest, current)}


def _close_line(s, date: str, sv: dict) -> str:
    """The ping/day_log line: base summary + reviews due + streak numbers, and
    a TASTELOG MISSING flag when the day had sessions but no judgment row."""
    line = (f"{_summary(s, date)}, {_reviews_due_count(s, date)} reviews due"
            f" · streak {sv['current_streak']} (best {sv['longest_streak']})")
    has_sessions = s.query(WorkSession).filter(WorkSession.date == date).count() > 0
    if has_sessions and not s.get(TasteLog, date):
        line += " · TASTELOG MISSING"
    return line


class DayCloseIn(BaseModel):
    timer_honored: bool | None = None


@app.post("/api/day/close")
def close_day(body: DayCloseIn | None = None, s=Depends(db)):
    date = today()
    row = s.get(DayLog, date)
    # timer_honored is earned by a completed struggle_timer session; an explicit
    # body value still overrides it (manual/test escape hatch).
    th = (body.timer_honored if body and body.timer_honored is not None
          else _timer_honored(s, date))
    sv = _streak_values(s, date, th)
    line = _close_line(s, date, sv)
    if row and row.summary_line == line:  # idempotent: same state, no second ping
        return {"summary_line": line, "pinged": row.pinged, "already_closed": True,
                "current_streak": sv["current_streak"],
                "longest_streak": sv["longest_streak"]}
    pinged = _ping(line)
    row = row or DayLog(date=date)
    row.summary_line, row.pinged, row.timer_honored = line, pinged, th
    row.streak_day, row.grace_used = sv["streak_day"], sv["grace_used"]
    row.current_streak, row.longest_streak = sv["current_streak"], sv["longest_streak"]
    s.merge(row)
    s.commit()
    infra.backup(DB_PATH, date)  # never blocks: backup() swallows its own errors
    return {"summary_line": line, "pinged": pinged, "already_closed": False,
            "current_streak": sv["current_streak"],
            "longest_streak": sv["longest_streak"]}


@app.get("/api/streak")
def streak(s=Depends(db)):
    row = s.query(DayLog).order_by(DayLog.date.desc()).first()
    # closed_today: the frontend's only backend-truth source for "is today's
    # file already closed" — without it, App.jsx's `closed` flag lived purely
    # in React state and reverted to false on every reload/reopen even though
    # the day was genuinely closed (bug: "completed day doesn't show as
    # complete"). See SESSION_LOG.md.
    return {"current_streak": row.current_streak if row else 0,
            "longest_streak": row.longest_streak if row else 0,
            "closed_today": bool(row and row.date == today())}


@app.get("/api/streak/today")
def streak_today(s=Depends(db)):
    """The three streak conditions, evaluated PROVISIONALLY for today.

    Read-only and deliberately NON-PERSISTING: decisions.md is explicit that
    the streak is computed only at day-close, and writing a day_log row here
    would make `_catch_up` treat today as already closed. This recomputes the
    same predicates `_streak_values` uses so the UI can show which conditions
    are met and — the point — which are still fixable before closing, instead
    of the streak being a verdict you only see afterwards.

    `fixable` distinguishes a condition you can still satisfy today (start and
    finish the timer, grade the overdue review) from one that is already
    settled (a task that ended failed_final cannot be un-failed today)."""
    date = today()
    th = _timer_honored(s, date)
    failed_final = s.query(Task).filter(
        Task.date == date, Task.status == "failed_final").count() > 0
    cutoff = (dt.date.fromisoformat(date)
              - dt.timedelta(days=MAX_OVERDUE_STREAK_DAYS)).isoformat()
    overdue = s.query(Review).filter(
        Review.status == "due", Review.due_date < cutoff).count() > 0
    return {
        "date": date,
        "streak_day": th and not failed_final and not overdue,
        "grace_available": not _grace_used_this_week(s, date),
        "conditions": [
            {"key": "timer", "met": th, "fixable": True,
             "label": "Finish a struggle timer for its planned minutes"},
            {"key": "no_failed_final", "met": not failed_final, "fixable": False,
             "label": "No exhibit failed twice"},
            {"key": "reviews_current", "met": not overdue, "fixable": True,
             "label": f"No review overdue by more than {MAX_OVERDUE_STREAK_DAYS} days"},
        ],
    }


def _opt(fn, default):
    """Run an optional-table section; skip (not crash) if its table is absent."""
    try:
        return fn()
    except Exception:
        infra.log.exception("export: optional section skipped")
        return default


def _by_date(rows):
    g: dict[str, list] = {}
    for r in rows:
        g.setdefault(r.date, []).append(r)
    return g


def _export_markdown(s, from_: str, to: str) -> str:
    """The weekly artifact. Core tables (tasks/recordings/day_log/vocab/drift/
    audit) are always present; sessions, tastelog and syntheses are optional and
    each wrapped so a build without them still assembles."""
    dset = {d for (d,) in s.query(Task.date).filter(Task.type != "reflection")
            .union(s.query(Recording.date)).union(s.query(DayLog.date))}
    dset |= _opt(lambda: {d for (d,) in s.query(WorkSession.date)}, set())
    dset |= _opt(lambda: {d for (d,) in s.query(TasteLog.date)}, set())
    dates = sorted(d for d in dset if from_ <= d <= to)
    sessions = _opt(lambda: _by_date(s.query(WorkSession).order_by(WorkSession.id)), {})
    tastes = _opt(lambda: {tl.date: tl for tl in s.query(TasteLog)}, {})

    out = [f"# Gatekeeper {from_} → {to}", ""]
    for date in dates:
        log = s.get(DayLog, date)
        head = f"## {date}"
        if log:
            head += f" — {log.summary_line}" + (" *(closed late)*" if log.late else "")
        else:
            head += " — never closed"
        out.append(head)
        for t in (s.query(Task).filter(Task.date == date, Task.type != "reflection")
                  .order_by(Task.id)):
            line = f"- [{t.status}] ({t.type}) {t.title}"
            if t.verdict:
                line += f" — {t.verdict}: {t.reason}"
            out.append(line)
        for r in s.query(Recording).filter(Recording.date == date).order_by(Recording.id):
            line = (f"- [recording:{r.status}] {r.duration_sec}s, "
                    f"audit {'read' if r.audit_viewed else 'UNREAD'}")
            if r.wpm is not None:
                line += (f" — {r.wpm} wpm, {r.fillers_per_min} fillers/min, "
                         f"unique ratio {r.unique_ratio}")
                if r.longest_silence_sec is not None:
                    line += f", longest silence {r.longest_silence_sec}s"
            out.append(line)
        for sess in sessions.get(date, []):
            actual = "—" if sess.actual_minutes is None else sess.actual_minutes
            line = f"- [session:{sess.kind}] {actual}/{sess.planned_minutes} min"
            if sess.aborted:
                line += f" ABORTED ({sess.abort_trigger})"
            out.append(line)
        tl = tastes.get(date)
        if tl and (tl.understood or tl.sticking_point):
            line = f"- [reflection] understood: {tl.understood or '—'}"
            if tl.sticking_point:
                line += f" | stuck: {tl.sticking_point}"
            out.append(line)
        elif tl:  # legacy drift/dread experiment rows
            out.append(f"- [tastelog] drift→{tl.drift_arm}, dread→{tl.dread_arm}: {tl.one_liner}")
        out.append("")

    flags = s.query(VocabFlag).order_by(VocabFlag.id).all()
    out.append("## Vocabulary ledger (cumulative error profile)")
    out += [f"- '{v.term_used}' used for '{v.term_meant}' — {v.date} ({v.source})"
            for v in flags] or ["- (empty)"]
    out.append("")
    out.append("## Drift report (independent re-grades that flipped PASS → FAIL)")
    drifts = s.query(DriftReport).filter(DriftReport.date >= from_,
                                         DriftReport.date <= to).all()
    out += [f"- {d.date}: task {d.task_id} → {d.new_verdict} — {d.new_reason} "
            f"(original pass reason: {d.original_reason})" for d in drifts] \
        or ["- no drift detected"]
    out.append("")
    out.append("## Evaluator audit trail")
    calls = (s.query(LLMCall).filter(LLMCall.ts >= from_, LLMCall.ts <= to + "T~")
             .order_by(LLMCall.id).all())
    for purpose in sorted({c.purpose for c in calls}):
        n = sum(c.purpose == purpose for c in calls)
        out.append(f"- {purpose}: {n} call(s)")
    out += [f"  - {c.ts} {c.purpose}"
            + (f" task {c.task_id}" if c.task_id else "")
            + (f" → {c.parsed_verdict}" if c.parsed_verdict else "")
            for c in calls] or ["- no calls in range"]
    syn = _opt(lambda: s.query(Synthesis).filter(Synthesis.week_start >= from_,
               Synthesis.week_start <= to).order_by(Synthesis.week_start).all(), [])
    if syn:
        out += ["", "## Weekly synthesis"]
        for x in syn:
            out += [f"### Week of {x.week_start} (generated {x.created_at})", x.content]
    return "\n".join(out)


@app.get("/api/export")
def export(from_: str | None = Query(None, alias="from"),
           to: str | None = None, s=Depends(db)):
    """Weekly-review artifact: day logs + task outcomes as markdown."""
    try:
        to = to or today()
        from_ = from_ or (dt.date.fromisoformat(to) - dt.timedelta(days=6)).isoformat()
        dt.date.fromisoformat(from_)
    except ValueError:
        raise HTTPException(422, "from/to must be YYYY-MM-DD")
    return PlainTextResponse(_export_markdown(s, from_, to), media_type="text/markdown")


@app.get("/api/week")
def week():
    try:
        return yaml.safe_load((ROOT / "week.yaml").read_text()) or {}
    except FileNotFoundError:
        return {}


# ---- editable current-week theme ----------------------------------------
# week.yaml's theme is the plan's default and can go stale (its week_of drifts
# out of the current week). The owner can override it with their own text; the
# label is computed from TODAY's ISO week so it's never a stale number.
_THEME_KEY = "week_theme"


@app.get("/api/theme")
def get_theme(s=Depends(db)):
    row = s.get(AppSetting, _THEME_KEY)
    plan = ((week().get("themes") or [""]) or [""])[0]
    custom = row.value if (row and row.value) else None
    return {"theme": custom if custom is not None else plan,
            "custom": custom is not None,
            "plan_theme": plan,
            "week": dt.date.fromisoformat(today()).isocalendar()[1]}


class ThemeIn(BaseModel):
    theme: str


@app.put("/api/theme")
def set_theme(body: ThemeIn, s=Depends(db)):
    """Set the owner's own theme. An empty string clears the override, reverting
    to the plan's week.yaml theme."""
    text = body.theme.strip()
    row = s.get(AppSetting, _THEME_KEY)
    if not text:                                   # clear → revert to plan
        if row:
            s.delete(row)
    elif row:
        row.value = text
    else:
        s.add(AppSetting(key=_THEME_KEY, value=text))
    s.commit()
    return get_theme(s)


@app.get("/api/history")
def history(s=Depends(db)):
    # A day with only an end-of-day reflection (no task/recording) still belongs
    # in History, so union in tastelog dates — but NOT reflection anchor tasks
    # (those would double-count and, in _catch_up, spuriously late-close a day).
    # DayLog dates are unioned in too: a day that was closed (even with only a
    # timer or reflection) is part of the record and must show in History and
    # feed the momentum grid, not vanish just because it filed no Task.
    dates = sorted({d for (d,) in s.query(Task.date)
                    .filter(Task.type != "reflection").union(s.query(Recording.date))
                    .union(s.query(TasteLog.date)).union(s.query(DayLog.date))}, reverse=True)
    out = []
    for date in dates:
        recs = []
        for r in s.query(Recording).filter(Recording.date == date).order_by(Recording.id):
            recs.append(_recording_dict(r))
        log = s.get(DayLog, date)
        try:  # per-day focus minutes from completed, non-aborted work sessions
            _sess = s.query(WorkSession).filter(WorkSession.date == date).all()
            focus_minutes = round(sum((w.actual_minutes or 0) for w in _sess
                                      if not w.aborted and w.actual_minutes), 1)
        except Exception:
            focus_minutes = 0
        tl = s.get(TasteLog, date)
        reflection = None
        if tl and (tl.understood or tl.sticking_point or tl.one_liner):
            # understood is the live field; fall back to the legacy one_liner so
            # old drift/dread-era rows still show their line.
            reflection = {"understood": tl.understood or tl.one_liner,
                          "sticking_point": tl.sticking_point}
        out.append({"date": date,
                    "tasks": [t.as_dict() for t in
                              s.query(Task).filter(Task.date == date,
                                                   Task.type != "reflection").order_by(Task.id)],
                    "recordings": recs,
                    "reflection": reflection,
                    "summary_line": log.summary_line if log else None,
                    "streak_day": bool(log.streak_day) if log else None,
                    "current_streak": log.current_streak if log else None,
                    "focus_minutes": focus_minutes})
    return out


# ---- roadmap (read-only 90-day case strategy) ---------------------------
# The plan lives in roadmap.json at the repo root; ROADMAP_PATH overrides it.
# A missing or malformed file yields an empty roadmap rather than a 500, so the
# ROADMAP tab shows a clean "no roadmap on file" state instead of an error.
def _roadmap_json() -> dict:
    path = Path(os.getenv("ROADMAP_PATH", str(ROOT / "roadmap.json")))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _roadmap_ticket_ids(data: dict) -> set[str]:
    return {t["id"] for p in data.get("phases", []) for t in p.get("tickets", [])
            if "id" in t}


def _valid_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


@app.get("/api/roadmap")
def roadmap(s=Depends(db)):
    """The plan (roadmap.json) merged with per-ticket DB state. Each ticket
    gains `status`/`done_date` and an EFFECTIVE `deadline`: the user's override
    when set, the user's explicit clear ('' = no deadline) when cleared, else
    the plan's own deadline. `plan_deadline` preserves the original so the UI
    can offer 'revert to plan'."""
    data = _roadmap_json()
    if not data.get("meta"):
        return {"meta": None, "phases": []}
    state = {r.ticket_id: r for r in s.query(RoadmapTicket).all()}
    for p in data.get("phases", []):
        for t in p.get("tickets", []):
            row = state.get(t.get("id"))
            t["plan_deadline"] = t.get("deadline")
            t["status"] = row.status if row else "open"
            t["done_date"] = row.done_date if row else ""
            if row is not None and row.deadline is not None:
                t["deadline"] = row.deadline  # override or explicit clear ('')
    return {"meta": data.get("meta"), "phases": data.get("phases", [])}


class RoadmapTicketUpdate(BaseModel):
    status: str | None = None            # 'open' | 'done'
    deadline: str | None = None          # a YYYY-MM-DD date, or '' for no deadline
    revert_deadline: bool = False        # drop the override, use the plan's date

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in ("open", "done"):
            raise ValueError("status must be 'open' or 'done'")
        return v


@app.post("/api/roadmap/tickets/{ticket_id}")
def update_roadmap_ticket(ticket_id: str, body: RoadmapTicketUpdate,
                          s=Depends(db)):
    if ticket_id not in _roadmap_ticket_ids(_roadmap_json()):
        raise HTTPException(404, "no such ticket in roadmap.json")
    if body.deadline not in (None, "") and not _valid_date(body.deadline):
        raise HTTPException(422, "deadline must be YYYY-MM-DD or '' to clear")
    row = s.get(RoadmapTicket, ticket_id)
    if row is None:
        row = RoadmapTicket(ticket_id=ticket_id)
        s.add(row)
    if body.status is not None:
        row.status = body.status
        row.done_date = today() if body.status == "done" else ""
    if body.revert_deadline:
        row.deadline = None                       # fall back to the plan's date
    elif body.deadline is not None:
        row.deadline = body.deadline              # set, or '' to clear
    row.updated_ts = clock.now_utc().isoformat(timespec="seconds")
    s.commit()
    return {"ticket_id": ticket_id, "status": row.status,
            "done_date": row.done_date, "deadline": row.deadline}


@app.post("/api/roadmap/reset")
def reset_roadmap(s=Depends(db)):
    """Clear the stale all-overdue state in one move: every ticket goes back to
    'open' with NO deadline (''), so nothing reads overdue and the user can set
    fresh deadlines. Upserts a row per ticket so the clear is explicit, not a
    fallthrough to the plan's (past) dates."""
    ids = _roadmap_ticket_ids(_roadmap_json())
    now = clock.now_utc().isoformat(timespec="seconds")
    existing = {r.ticket_id: r for r in s.query(RoadmapTicket).all()}
    for tid in ids:
        row = existing.get(tid) or RoadmapTicket(ticket_id=tid)
        row.status, row.done_date, row.deadline, row.updated_ts = "open", "", "", now
        s.add(row)
    s.commit()
    return {"reset": len(ids)}


# ---- daily operating protocol (read-only) -------------------------------
# The daily routine lives in Daily_protocol.json at the repo root;
# PROTOCOL_PATH overrides it. A missing/malformed file yields {} so the
# PROTOCOL tab shows a clean empty state rather than a 500.
@app.get("/api/protocol")
def protocol():
    path = Path(os.getenv("PROTOCOL_PATH", str(ROOT / "Daily_protocol.json")))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


# ---- daily habits (the non-negotiables, made tickable) --------------------
# The protocol's own motto is "track inputs, not outcomes" — a non-negotiable
# IS an input, so ticking one is the motto's purest expression, not a departure
# from it. The habit definitions stay in Daily_protocol.json (single source of
# truth for what the rules ARE); only the ticks live in the DB.
HABIT_WINDOW = 7  # days shown in the per-habit strip


def _habit_defs() -> list[dict]:
    """The non-negotiables, in file order. Ids are required and stable."""
    out = []
    for i, n in enumerate(protocol().get("non_negotiables", [])):
        hid = n.get("id") or f"nn{i + 1}"
        out.append({"id": hid, "title": n.get("title", ""),
                    "explanation": n.get("explanation", "")})
    return out


def _habit_streak(done_dates: set[str], date: str) -> int:
    """Consecutive days ending at `date`. Today not being ticked YET doesn't
    break the streak — a day is only a miss once it's over, so we start the walk
    at yesterday when today is unticked. Otherwise every morning would show 0
    and the number would be useless as a motivator."""
    d = dt.date.fromisoformat(date)
    if date not in done_dates:
        d -= dt.timedelta(days=1)
    n = 0
    while d.isoformat() in done_dates:
        n += 1
        d -= dt.timedelta(days=1)
    return n


@app.get("/api/habits")
def habits(s=Depends(db)):
    """Today's non-negotiables with tick state, streak, and a 7-day strip.
    `target_pct` comes from the protocol's own success_bar ("70% of days") — the
    UI marks it so the bar reads as 'the system is working', not 'you failed to
    hit 100%'."""
    date = today()
    defs = _habit_defs()
    ids = [h["id"] for h in defs]
    rows = (s.query(HabitLog)
            .filter(HabitLog.habit_id.in_(ids), HabitLog.done.is_(True)).all()
            if ids else [])
    by_habit: dict[str, set[str]] = {}
    for r in rows:
        by_habit.setdefault(r.habit_id, set()).add(r.date)

    window = [(dt.date.fromisoformat(date) - dt.timedelta(days=i)).isoformat()
              for i in range(HABIT_WINDOW - 1, -1, -1)]
    out = []
    for h in defs:
        done_dates = by_habit.get(h["id"], set())
        out.append({**h,
                    "done": date in done_dates,
                    "streak": _habit_streak(done_dates, date),
                    "week": [{"date": d, "done": d in done_dates} for d in window]})
    done_today = sum(h["done"] for h in out)
    return {"date": date, "habits": out,
            "done_today": done_today, "total": len(out),
            "target_pct": _target_pct()}


def _target_pct() -> int:
    """Parse the first percentage out of the protocol's success_bar sentence
    ('Hitting 70% of days = the system is working'). Falls back to 70 — the
    point is that the bar has a realistic mark, never that it demands 100%."""
    m = re.search(r"(\d{1,3})\s*%", protocol().get("success_bar", "") or "")
    return int(m.group(1)) if m else 70


class HabitToggle(BaseModel):
    done: bool | None = None  # omitted = flip whatever it is now


@app.post("/api/habits/{habit_id}/toggle")
def toggle_habit(habit_id: str, body: HabitToggle | None = None, s=Depends(db)):
    if habit_id not in {h["id"] for h in _habit_defs()}:
        raise HTTPException(404, "no such habit in Daily_protocol.json")
    date = today()
    row = s.get(HabitLog, {"date": date, "habit_id": habit_id})
    want = (not (row.done if row else False)) if (body is None or body.done is None) \
        else body.done
    if row is None:
        row = HabitLog(date=date, habit_id=habit_id)
        s.add(row)
    row.done = want
    row.ts = clock.now_utc().isoformat(timespec="seconds")
    s.commit()
    return {"habit_id": habit_id, "date": date, "done": row.done}


# Serve the built frontend (production). Mounted LAST so every /api route above
# takes precedence; skipped in local dev where the Vite dev server serves the UI
# and this directory doesn't exist.
_STATIC = os.getenv("SENTINEL_STATIC", str(ROOT / "frontend" / "dist"))
if Path(_STATIC).is_dir():
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="frontend")
