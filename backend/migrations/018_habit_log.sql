-- Habit tracking for the daily non-negotiables (HABITS tab, formerly PROTOCOL).
--
-- One row per (date, habit_id) that has ever been ticked. Absence of a row means
-- "not done" — we never pre-seed a day, so a day the app wasn't opened is simply
-- empty rather than a wall of false FAILs.
--
-- habit_id is the STABLE id from Daily_protocol.json (nn1..nn5), never the title
-- text: rewording a non-negotiable must not orphan its history.
CREATE TABLE IF NOT EXISTS habit_log (
    date     TEXT NOT NULL,          -- local ISO date, matches day_log.date
    habit_id TEXT NOT NULL,          -- Daily_protocol.json non_negotiables[].id
    done     INTEGER NOT NULL DEFAULT 0,
    ts       TEXT NOT NULL DEFAULT '',  -- UTC iso of the last toggle, for audit
    PRIMARY KEY (date, habit_id)
);

CREATE INDEX IF NOT EXISTS idx_habit_log_habit ON habit_log (habit_id, date);
