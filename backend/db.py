"""SQLite models + server-side enforcement.

The state machine, field immutability, the one-retry rule, and the
max-3-gated-tasks rule all live HERE, so no route (or future bug in one)
can complete a task illegally. Routes translate GamingError → HTTP status.
"""
import os
from pathlib import Path

from sqlalchemy import (Boolean, Float, Integer, String, Text, create_engine,
                        event)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            sessionmaker, validates)

import infra
from infra import DATA_DIR  # re-export for callers  # noqa: F401

DB_PATH = os.getenv("GATEKEEPER_DB", str(DATA_DIR / "gatekeeper.db"))

engine = create_engine(f"sqlite:///{DB_PATH}",
                       connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# --- Concurrency correctness (C1) -------------------------------------------
# The default DEFERRED transactions take the write lock only at first WRITE, so
# two requests can both READ stale state (attempts=0, answer="") and proceed.
# We do NOT force BEGIN IMMEDIATE globally: routes call the LLM mid-request, and
# the audit trail (llm._record) writes an LLMCall row on a SEPARATE connection
# during that window — a request-wide write lock would deadlock against it.
# Instead the write-conflict is resolved at the DB layer, lock-free: the answers
# UNIQUE(task_id, attempt_no) and the compare-and-set UPDATEs in main.py mean
# two racing writers can never both commit a conflicting change (the loser hits
# a UNIQUE/BUSY_SNAPSHOT error or a 0-row update → 409). busy_timeout makes a
# concurrent writer queue on the write lock rather than fail instantly.
@event.listens_for(engine, "connect")
def _pragmas(conn, _rec):
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()

MAX_GATED_PER_DAY = 3
MAX_ATTEMPTS = 2  # one retry per day
MAX_REVIEWS = 3   # spaced-repetition reviews per source task, then retire
SESSION_KINDS = ("struggle_timer", "training_arm", "eval_arm", "decode", "verbal_prep")
SESSION_MAX_HOURS = 6  # an open session older than this is auto-aborted
ARMS = ("training", "eval", "none")  # tastelog attribution targets
# RECALL remediation tasks (spawned when a review is self-graded 'forgot') are
# exempt from the gated-per-day cap: they are MORE friction, not less, so they
# can't be abused to dodge the limit, and an honest 'forgot' must never be
# blocked by an unrelated cap. See decisions.md.
RECALL_PREFIX = "RECALL: "


class GamingError(Exception):
    """Base for every server-side enforcement rejection."""


class IllegalTransition(GamingError):
    pass


class ImmutableField(GamingError):
    pass


class GatedLimitExceeded(GamingError):
    pass


# The complete set of legal status transitions, per task type.
LEGAL_TRANSITIONS = {
    "simple": {("open", "done")},
    "gated": {("open", "passed"), ("open", "failed_once"),
              ("failed_once", "passed"), ("failed_once", "failed_final")},
}
CLOSED_STATUSES = ("done", "passed", "failed_final")


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)            # simple | gated
    status: Mapped[str] = mapped_column(String, default="open")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    artifact: Mapped[str] = mapped_column(Text, default="")
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(Text, default="")

    @validates("status")
    def _v_status(self, _k, new):
        old = self.status
        if old is None:  # object under construction
            if new != "open":
                raise IllegalTransition(f"new tasks start 'open', not {new!r}")
            return new
        if new == old:
            return new
        if (old, new) not in LEGAL_TRANSITIONS.get(self.type, set()):
            raise IllegalTransition(f"{self.type} task cannot go {old} → {new}")
        infra.log.info("task %s (%s): %s -> %s", self.id, self.title, old, new)
        return new

    @validates("artifact")
    def _v_artifact(self, _k, new):
        if self.status in CLOSED_STATUSES:
            raise ImmutableField("task is closed — artifact is frozen")
        if self.artifact and self.question and not self.answer:
            raise ImmutableField("artifact is frozen while its question is pending")
        return new

    @validates("question")
    def _v_question(self, _k, new):
        if self.status in CLOSED_STATUSES:
            raise ImmutableField("task is closed — question is frozen")
        if self.question and not self.answer and new != self.question:
            raise ImmutableField("a pending question cannot be swapped")
        return new

    @validates("answer")
    def _v_answer(self, _k, new):
        old = self.answer
        if old and new != old:
            # Clearing is legal only as part of opening a fresh attempt,
            # i.e. after the previous attempt received a verdict.
            if new == "" and self.verdict:
                return new
            raise ImmutableField("a submitted answer can never be modified")
        return new

    @validates("attempts")
    def _v_attempts(self, _k, new):
        old = self.attempts or 0
        if new != old + 1:
            raise IllegalTransition("attempts can only increment by one")
        if new > MAX_ATTEMPTS:
            raise IllegalTransition(
                f"max {MAX_ATTEMPTS} evaluation attempts per task per day")
        return new

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("id", "date", "title", "type", "status", "attempts",
                 "artifact", "question", "answer", "verdict", "reason")}


class Answer(Base):
    """Append-only ledger of every submitted answer (C1 belt-and-suspenders).

    UNIQUE(task_id, attempt_no) is the DB-level atomic guard: two racing
    submissions computing the same attempt_no can never both persist, even if
    the BEGIN IMMEDIATE serialization is ever defeated. Rows are immutable and
    undeletable (enforced by triggers in migration 014), so a submitted answer
    can never be rewritten. The current answer still lives on tasks.answer;
    this table only makes the invariant unforgeable."""
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    answer_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String, index=True)
    duration_sec: Mapped[int] = mapped_column(Integer)
    audio_path: Mapped[str] = mapped_column(String)
    transcript_path: Mapped[str] = mapped_column(String)
    audit_path: Mapped[str] = mapped_column(String)
    audit_viewed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="uploaded")
    # uploaded | transcription_failed | audit_failed | done
    wpm: Mapped[float | None] = mapped_column(Float, default=None)
    fillers_per_min: Mapped[float | None] = mapped_column(Float, default=None)
    unique_ratio: Mapped[float | None] = mapped_column(Float, default=None)
    longest_silence_sec: Mapped[float | None] = mapped_column(Float, default=None)

    @validates("audit_viewed")
    def _v_viewed(self, _k, new):
        if self.audit_viewed and not new:
            raise ImmutableField("audit_viewed cannot be revoked")
        if new and not (self.audit_path and Path(self.audit_path).exists()):
            raise IllegalTransition("audit cannot be marked viewed before it exists")
        return new

    @validates("status")
    def _v_rec_status(self, _k, new):
        if self.status and new != self.status:
            infra.log.info("recording %s: %s -> %s", self.id, self.status, new)
        return new

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("id", "date", "duration_sec", "audio_path",
                 "transcript_path", "audit_path", "audit_viewed", "status",
                 "wpm", "fillers_per_min", "unique_ratio", "longest_silence_sec")}


class LLMCall(Base):
    """Audit trail: nothing the evaluator does is ephemeral."""
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String, index=True)
    purpose: Mapped[str] = mapped_column(String)
    task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    prompt_hash: Mapped[str] = mapped_column(String)
    response: Mapped[str] = mapped_column(Text)
    parsed_verdict: Mapped[str] = mapped_column(String, default="")


class VocabFlag(Base):
    """Compounding personal error profile of imprecise vocabulary."""
    __tablename__ = "vocab_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_used: Mapped[str] = mapped_column(String)
    term_meant: Mapped[str] = mapped_column(String)
    date: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)


class DriftReport(Base):
    __tablename__ = "drift_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String)
    task_id: Mapped[int] = mapped_column(Integer)
    original_reason: Mapped[str] = mapped_column(Text)
    new_verdict: Mapped[str] = mapped_column(String)
    new_reason: Mapped[str] = mapped_column(Text)


class Review(Base):
    """A scheduled spaced-repetition retrieval of a passed gated task.

    Flow is enforced server-side in one direction only: reveal (stamps
    revealed_at) → grade (immutable once written, illegal before reveal).
    Same immutability spirit as Task.answer.
    """
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_task_id: Mapped[int] = mapped_column(Integer, index=True)
    due_date: Mapped[str] = mapped_column(String, index=True)
    fsrs_card_state: Mapped[str] = mapped_column(Text)  # JSON of the state that scheduled this review
    status: Mapped[str] = mapped_column(String, default="due")   # due | done
    grade: Mapped[str] = mapped_column(String, default="")       # recalled|partial|forgot|""
    revealed_at: Mapped[str] = mapped_column(String, default="")
    graded_at: Mapped[str] = mapped_column(String, default="")

    @validates("status")
    def _v_rev_status(self, _k, new):
        old = self.status
        if old is None or new == old:
            return new
        if (old, new) != ("due", "done"):
            raise IllegalTransition(f"review cannot go {old} → {new}")
        return new

    @validates("revealed_at")
    def _v_revealed(self, _k, new):
        if self.revealed_at and new != self.revealed_at:
            raise ImmutableField("revealed_at is stamped once and cannot change")
        return new

    @validates("grade")
    def _v_grade(self, _k, new):
        if self.grade and new != self.grade:
            raise ImmutableField("a submitted grade can never be modified")
        if new:
            if new not in ("recalled", "partial", "forgot"):
                raise IllegalTransition(f"invalid grade {new!r}")
            if not self.revealed_at:
                raise IllegalTransition("cannot grade a review before revealing it")
        return new

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("id", "source_task_id", "due_date", "status", "grade",
                 "revealed_at", "graded_at")}


class WorkSession(Base):
    """A timed work block. `struggle_timer` sessions that meet their planned
    minutes are what earn timer_honored (see main._timer_honored)."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    planned_minutes: Mapped[int] = mapped_column(Integer)
    actual_minutes: Mapped[float | None] = mapped_column(Float, default=None)
    started_at: Mapped[str] = mapped_column(String)
    ended_at: Mapped[str] = mapped_column(String, default="")  # "" while running
    aborted: Mapped[bool] = mapped_column(Boolean, default=False)
    abort_trigger: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("id", "date", "kind", "planned_minutes", "actual_minutes",
                 "started_at", "ended_at", "aborted", "abort_trigger", "notes")}


class TasteLog(Base):
    """One immutable end-of-day judgment row per date (existing immutability
    pattern: fields freeze once written; a second POST for the date is a 409)."""
    __tablename__ = "tastelog"
    date: Mapped[str] = mapped_column(String, primary_key=True)
    drift_arm: Mapped[str] = mapped_column(String)   # training | eval | none
    dread_arm: Mapped[str] = mapped_column(String)   # training | eval | none
    one_liner: Mapped[str] = mapped_column(Text)

    @validates("drift_arm", "dread_arm", "one_liner")
    def _immutable(self, key, new):
        old = getattr(self, key)
        if old and new != old:
            raise ImmutableField(f"tastelog.{key} is immutable once written")
        return new

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("date", "drift_arm", "dread_arm", "one_liner")}


class DayLog(Base):
    __tablename__ = "day_log"
    date: Mapped[str] = mapped_column(String, primary_key=True)
    summary_line: Mapped[str] = mapped_column(Text)
    pinged: Mapped[bool] = mapped_column(Boolean, default=False)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    # quality streak (computed ONLY server-side at day-close)
    streak_day: Mapped[bool] = mapped_column(Boolean, default=False)
    timer_honored: Mapped[bool] = mapped_column(Boolean, default=True)
    grace_used: Mapped[bool] = mapped_column(Boolean, default=False)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)


class Glossary(Base):
    """Decoded notation. Overloaded symbols are surfaced, never deduplicated:
    the same symbol with a different meaning flags is_overload on every row
    that shares it."""
    __tablename__ = "glossary"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    type_annotation: Mapped[str] = mapped_column(String, default="")
    meaning: Mapped[str] = mapped_column(Text)
    source_paper: Mapped[str] = mapped_column(String, default="")
    first_seen_date: Mapped[str] = mapped_column(String)
    is_overload: Mapped[bool] = mapped_column(Boolean, default=False)

    def as_dict(self):
        return {c: getattr(self, c) for c in
                ("id", "symbol", "type_annotation", "meaning", "source_paper",
                 "first_seen_date", "is_overload")}


class Synthesis(Base):
    """One LLM weekly synthesis per ISO-week start."""
    __tablename__ = "syntheses"
    week_start: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)


def _counts_toward_cap(t: "Task") -> bool:
    return t.type == "gated" and not t.title.startswith(RECALL_PREFIX)


@event.listens_for(SessionLocal, "before_flush")
def _enforce_gated_limit(session, _ctx, _instances):
    new_gated = [o for o in session.new
                 if isinstance(o, Task) and _counts_toward_cap(o)]
    with session.no_autoflush:
        for t in new_gated:
            existing = (session.query(Task)
                        .filter(Task.date == t.date, Task.type == "gated",
                                ~Task.title.like(RECALL_PREFIX + "%")).count())
            pending = sum(1 for o in new_gated if o.date == t.date)
            if existing + pending > MAX_GATED_PER_DAY:
                raise GatedLimitExceeded(
                    f"max {MAX_GATED_PER_DAY} gated tasks per day")


infra.migrate(engine)
