CREATE TABLE IF NOT EXISTS drift_reports (
  id INTEGER NOT NULL PRIMARY KEY,
  date VARCHAR NOT NULL,
  task_id INTEGER NOT NULL,
  original_reason TEXT NOT NULL,
  new_verdict VARCHAR NOT NULL,
  new_reason TEXT NOT NULL
)
