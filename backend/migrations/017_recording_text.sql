-- 017: persist transcript + audit text in the DB.
-- On a host with an ephemeral disk (Hugging Face free), the recording's
-- transcript/audit FILES do not survive a restart, but the SQLite DB does
-- (Litestream replicates it to Supabase). Storing the text here means the
-- audit shown in History survives. Existing rows keep '' and History falls
-- back to reading the file, so this is backward-compatible.
ALTER TABLE recordings ADD COLUMN transcript_text TEXT NOT NULL DEFAULT '';
ALTER TABLE recordings ADD COLUMN audit_text TEXT NOT NULL DEFAULT '';
