# Running todo

- [x] Step 1: backend skeleton + DB + task CRUD + simple completion — verified via curl
- [x] Step 2: gated flow end to end — verified with real NIM calls (PASS, FAIL, retry, lock)
- [x] Step 3: Today panel — verified rendering in headless Chrome
- [x] Step 4: recording panel — verified: 7:29 upload → whisper transcript → LLM audit → viewed-gate; short/garbage uploads rejected
- [x] Step 5: day close + ping — verified: public_log.md fallback, "verbal done" after audit read
- [x] Step 6: week.yaml display — verified via API + rendered strip
- [x] History panel (in-spec third panel)
- [x] README + smoke-test checklist

Nothing open. Next session: walk the README smoke test in the browser.

## Reliability follow-ups (from the audit_failed / lost-recording investigation, 2026-07-23)

- [x] **Close the residual data-loss window.** Tightened Litestream's
  `monitor-interval`/`sync-interval` from the 1s/1s defaults to 250ms/250ms
  (litestream.yml) — verified notify-driven (no idle S3 polling cost) and
  config-valid against the exact v0.3.13 binary the Dockerfile installs, and
  confirmed sub-second replication with a local file-replica run. Narrows,
  doesn't eliminate, the async-replication gap — full elimination would need
  a synchronous flush/ack before returning 200, not attempted.
- [x] **Give upload/retry errors a real recording id.** `_process` (backend/main.py)
  now attaches an `X-Recording-Id` header on every failure response; added
  `GET /api/recordings/{id}` for a direct point lookup. `Record.jsx`'s error
  path uses that id directly instead of guessing via a full `/api/history`
  scan (the guess-based path is kept only for the no-id mount-time case).
- [x] ~~Add a CI gate before autoDeploy.~~ Declined — no GitHub Actions/CI.
