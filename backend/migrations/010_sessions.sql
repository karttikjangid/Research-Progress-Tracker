CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER NOT NULL PRIMARY KEY,
  date VARCHAR NOT NULL,
  kind VARCHAR NOT NULL,
  planned_minutes INTEGER NOT NULL,
  actual_minutes FLOAT,
  started_at VARCHAR NOT NULL,
  ended_at VARCHAR NOT NULL,
  aborted BOOLEAN NOT NULL,
  abort_trigger TEXT NOT NULL,
  notes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_date ON sessions (date)
