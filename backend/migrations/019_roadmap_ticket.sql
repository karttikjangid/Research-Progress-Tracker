-- Per-ticket state for the ROADMAP page. The plan (topics, scope, proof gates)
-- stays read-only in roadmap.json; only the mutable bits — is-it-done and the
-- user's own deadline — live here, keyed by the ticket's STABLE id (A1, B2…) so
-- rewording a topic in the JSON never orphans its state.
--
-- deadline column, three meanings:
--   NULL  → no override; use the plan's own deadline from roadmap.json
--   ''    → the user explicitly cleared it; this ticket has NO deadline
--   date  → the user's own deadline, overriding the plan
CREATE TABLE IF NOT EXISTS roadmap_ticket (
    ticket_id  TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'done'
    done_date  TEXT NOT NULL DEFAULT '',       -- local ISO date it was marked done
    deadline   TEXT,                            -- see three-way meaning above
    updated_ts TEXT NOT NULL DEFAULT ''
);
