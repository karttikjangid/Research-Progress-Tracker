-- Generic single-user key/value settings store. First use: the editable weekly
-- theme override (the plan's week.yaml is stale/read-only; this lets the owner
-- set their own current-week theme without editing a file). Kept generic so
-- future small user-owned settings don't each need a table.
CREATE TABLE IF NOT EXISTS app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
