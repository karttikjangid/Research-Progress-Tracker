-- C1: append-only, immutable answer ledger.
-- UNIQUE(task_id, attempt_no) is the atomic backstop against two racing
-- submissions both persisting the same attempt. Triggers make a submitted
-- answer un-updatable and un-deletable at the DB layer.
CREATE TABLE IF NOT EXISTS answers (
  id INTEGER NOT NULL PRIMARY KEY,
  task_id INTEGER NOT NULL,
  attempt_no INTEGER NOT NULL,
  answer_text TEXT NOT NULL,
  created_at VARCHAR NOT NULL,
  UNIQUE (task_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS ix_answers_task_id ON answers (task_id);

CREATE TRIGGER IF NOT EXISTS answers_no_update
BEFORE UPDATE ON answers
BEGIN
  SELECT RAISE(ABORT, 'a submitted answer can never be modified');
END;

CREATE TRIGGER IF NOT EXISTS answers_no_delete
BEFORE DELETE ON answers
BEGIN
  SELECT RAISE(ABORT, 'a submitted answer can never be deleted');
END;

-- A grade, once written, is immutable at the DB layer too (mirrors the
-- reveal→grade one-way flow; belt-and-suspenders for concurrent /grade).
CREATE TRIGGER IF NOT EXISTS reviews_grade_immutable
BEFORE UPDATE ON reviews
WHEN OLD.grade <> '' AND NEW.grade <> OLD.grade
BEGIN
  SELECT RAISE(ABORT, 'a submitted grade can never be modified');
END;
