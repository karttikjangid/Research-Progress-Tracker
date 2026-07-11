ALTER TABLE recordings ADD COLUMN wpm REAL;
ALTER TABLE recordings ADD COLUMN fillers_per_min REAL;
ALTER TABLE recordings ADD COLUMN unique_ratio REAL;
ALTER TABLE recordings ADD COLUMN longest_silence_sec REAL
