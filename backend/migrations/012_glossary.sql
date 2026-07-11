CREATE TABLE IF NOT EXISTS glossary (
  id INTEGER NOT NULL PRIMARY KEY,
  symbol VARCHAR NOT NULL,
  type_annotation VARCHAR NOT NULL,
  meaning TEXT NOT NULL,
  source_paper VARCHAR NOT NULL,
  first_seen_date VARCHAR NOT NULL,
  is_overload BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_glossary_symbol ON glossary (symbol)
