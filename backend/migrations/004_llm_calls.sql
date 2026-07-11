CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER NOT NULL PRIMARY KEY,
  ts VARCHAR NOT NULL,
  purpose VARCHAR NOT NULL,
  task_id INTEGER,
  prompt_hash VARCHAR NOT NULL,
  response TEXT NOT NULL,
  parsed_verdict VARCHAR NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_ts ON llm_calls (ts)
