CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER NOT NULL PRIMARY KEY,
  date VARCHAR NOT NULL,
  title VARCHAR NOT NULL,
  type VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  attempts INTEGER NOT NULL,
  artifact TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  verdict VARCHAR NOT NULL,
  reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_date ON tasks (date);
CREATE TABLE IF NOT EXISTS recordings (
  id INTEGER NOT NULL PRIMARY KEY,
  date VARCHAR NOT NULL,
  duration_sec INTEGER NOT NULL,
  audio_path VARCHAR NOT NULL,
  transcript_path VARCHAR NOT NULL,
  audit_path VARCHAR NOT NULL,
  audit_viewed BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recordings_date ON recordings (date);
CREATE TABLE IF NOT EXISTS day_log (
  date VARCHAR NOT NULL PRIMARY KEY,
  summary_line TEXT NOT NULL,
  pinged BOOLEAN NOT NULL
)
