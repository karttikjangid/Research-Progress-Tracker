# Gatekeeper

Local-only accountability app: the daily to-do list is gated behind proof of
learning. See [Project.md](Project.md) for the full contract.

## Run on Kubuntu

Prereqs (one-time): Python 3.11+, Node 18+, `ffmpeg` (already standard on Kubuntu).

```bash
cd ~/Research\ Automation

# 0. Secrets (one-time) — .env is gitignored
cp .env.example .env   # then paste NVIDIA_API_KEY (and optionally Telegram vars)

# 1. Backend (one-time setup)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. Backend (every day) — terminal 1
cd backend && ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Frontend (one-time setup)
cd frontend && npm install

# 4. Frontend (every day) — terminal 2
cd frontend && npm run dev

# 5. Open the app
xdg-open http://localhost:5173
```

**First-run whisper model download:** the first recording upload downloads the
`small` faster-whisper model (~460 MB) from Hugging Face into `~/.cache/huggingface`.
The upload spinner will sit for a few minutes exactly once. To pre-download instead:

```bash
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

**23:00 auto-close (optional):** `crontab -e` and add

```
0 23 * * * curl -s -X POST http://127.0.0.1:8000/api/day/close > /dev/null
```

## Backend tests (anti-gaming suite)

```bash
.venv/bin/pip install -r backend/requirements-dev.txt   # one-time
cd backend && ../.venv/bin/python -m pytest tests/
```

## 5-minute smoke-test checklist

Backend + frontend running, `.env` has a valid `NVIDIA_API_KEY`.

**Flow 1 — simple task (~30 s)**
- [ ] Today panel: add a task, type `simple` → appears with status `open`
- [ ] Click **Done** → status flips to `done`, no questions asked

**Flow 2 — gated task end-to-end, real API (~2 min)**
- [ ] Add a task, type `gated` → **Done** button is absent; only **Complete (evaluated)**
- [ ] Click it, paste a real artifact (a derivation or diff, ≥80 chars; a topic name is rejected)
- [ ] A probing question derived from YOUR artifact appears (real NIM call)
- [ ] Answer vaguely on purpose → `FAIL` + one-line reason, task shows `failed_once`, **Retry (1 left)**
- [ ] Retry with a specific, committed answer → `PASS`, task shows `passed`
- [ ] Try adding a 4th gated task → red error "max 3 gated tasks per day"

**Flow 3 — recording → transcript → audit → unlock (~6 min, mostly talking)**
- [ ] Record panel: **Start**, talk ≥4:30 (stop button stays grey until then)
- [ ] Stop before 4:30 once → take discarded client-side with an error
- [ ] Full take → spinner → audit report appears (filler counts, died sentences, vocab, altitude)
- [ ] **Mark audit as read** is disabled until you scroll the report to the end
- [ ] After marking read → Today panel's Verbal drill row flips to `done`
- [ ] Files exist on disk: `data/audio/<today>/` has `.webm`, `.transcript.txt`, `.audit.md`

**Day close (~10 s)**
- [ ] Today panel: **Close day** → summary line shown, e.g. `Jul 10: 1/3 gated passed, 1/1 simple done, verbal done`
- [ ] No Telegram vars in `.env` → line appended to `public_log.md`; with them → arrives in the bot chat
- [ ] History panel shows the day: tasks with verdicts, recording with expandable audit
- [ ] Week strip at the top shows the `week.yaml` themes, read-only
