-- End-of-day reflection redesign: the tastelog stops being a drift/dread
-- self-experiment log and becomes a learning consolidation record. Two new
-- fields — what you understand now that you didn't this morning (retrieval),
-- and the day's hardest sticking point (which is scheduled as a review the next
-- day via the FSRS machinery). The legacy drift_arm/dread_arm/one_liner columns
-- are kept so historical rows and the /api/tastelog/verdict tally still work.
ALTER TABLE tastelog ADD COLUMN understood TEXT NOT NULL DEFAULT '';
ALTER TABLE tastelog ADD COLUMN sticking_point TEXT NOT NULL DEFAULT '';
