# Gatekeeper — build plan (maps MVP steps → files)

Budgets: backend ≤700 lines total, frontend ≤600 lines total. Localhost only.

## Layout (repo root)

```
backend/            FastAPI app (one uvicorn process)
  main.py           routes + app wiring
  db.py             SQLAlchemy models: tasks, recordings, day_log
  llm.py            NVIDIA NIM client (question gen, answer eval, transcript audit)
  transcribe.py     faster-whisper (small/int8, CPU fallback) + duration probe
  requirements.txt
frontend/           Vite + React + Tailwind, single page, three panels
  src/App.jsx       layout + panel switching
  src/api.js        fetch helpers
  src/Today.jsx     tasks, gated flow modal, verbal pseudo-task, day close
  src/Record.jsx    MediaRecorder → upload → audit report w/ scroll gate
  src/History.jsx   read-only chronological feed
prompts/            question_gen.txt, answer_eval.txt, transcript_audit.txt (verbatim)
week.yaml           hand-edited weekly themes (read-only in UI)
data/               SQLite db + audio/YYYY-MM-DD/ (gitignored)
.env                NVIDIA_API_KEY, EVAL_MODEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

## Step → file mapping (build order, verify each before next)

1. **Backend skeleton + DB + task CRUD + simple completion**
   `backend/db.py`, `backend/main.py` (GET/POST /api/tasks, POST /api/tasks/{id}/complete).
   Verify: uvicorn up, curl create/list/complete, 400 on 4th gated task.
2. **Gated flow end to end**
   `backend/llm.py`, routes /artifact and /answer, status machine
   open→passed | failed_once (one retry, new question, lock after 2nd FAIL).
   Verify: curl with real NIM call using .env key.
3. **Frontend Today panel**
   Vite scaffold, `Today.jsx` + `api.js`. Verify: renders, full gated flow in browser.
4. **Recording panel**
   `backend/transcribe.py`, /api/recordings + /viewed, `Record.jsx` with 4:30
   client+server rejection and scroll-to-bottom gate.
   Verify: real mic recording (or generated wav→webm), transcript + audit on disk.
5. **Day close + ping**
   /api/day/close → Telegram or public_log.md fallback. Verify: curl, line appears.
6. **week.yaml display**
   /api/week + header strip in App. Verify: themes render.

Then: README (Kubuntu commands, crontab line, first-run whisper download) +
smoke-test checklist. Spare time → tighten gated-flow error handling only.
