CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER NOT NULL PRIMARY KEY,
  source_task_id INTEGER NOT NULL,
  due_date VARCHAR NOT NULL,
  fsrs_card_state TEXT NOT NULL,
  status VARCHAR NOT NULL,
  grade VARCHAR NOT NULL,
  revealed_at VARCHAR NOT NULL,
  graded_at VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reviews_source ON reviews (source_task_id);
CREATE INDEX IF NOT EXISTS ix_reviews_due ON reviews (due_date)
