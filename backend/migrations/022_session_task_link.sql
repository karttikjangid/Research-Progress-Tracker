-- A running session's link to its task was previously reconstructed only
-- from the browser's localStorage cache, with no backend record of it. A
-- request delayed by a cold start (e.g. Render's free-tier spin-down/wake)
-- could outlive that cache, or race a reload before the cache was written —
-- the reconciliation logic then fell back to task_id=NULL, and the running
-- timer became invisible on every task card even though the session was
-- still open server-side. Making the link backend-authoritative removes the
-- fragile client-side guess entirely.
ALTER TABLE sessions ADD COLUMN task_id INTEGER;
