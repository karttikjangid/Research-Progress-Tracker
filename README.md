# Sentinel

**A private, single-user accountability instrument that gates your most demanding
daily work behind evidence of real effort — verified by an LLM examiner that
returns a strict PASS or FAIL, never a score.**

Sentinel is not a habit tracker and not a to-do list. It is an enforcement tool
built on one principle: **the day's hardest tasks stay locked until you produce
evidence that you actually did the work, and an impartial examiner judges that
evidence.** It exists to defeat the "AI copilot trap" — the slow erosion of skill
that comes from letting a model think for you — by forcing genuine cognitive
struggle and holding you to it.

---

## The idea

- **Evidence over intention.** A gated task is not "done" because you say so. You
  submit an artifact (a derivation, a diff, decode notes — real work), the
  examiner asks one pointed question derived from *your* artifact, and your answer
  is graded.
- **Binary verdicts, no scores.** Every gated verdict is `PASS` or `FAIL` with a
  single one-line reason. No numbers to optimize, no partial credit, no appeals.
- **One retry, then locked.** A failed task grants exactly one retry with a fresh,
  harder question. Fail twice and it is locked until tomorrow.
- **No gamification.** The only progress signal is a single, server-computed
  streak number. No badges, levels, or points.

## What it does

| Capability | Description |
|---|---|
| **Gated tasks** | Evidence → examiner question → final answer → `PASS`/`FAIL` + reason. One retry, then locked. Max three per day. |
| **Free ticks** | Lightweight self-certified items that carry no weight in the record. |
| **Verbal drill** | Record a single spoken take (min 4:30) → transcribed locally → the examiner audits fluency (filler rate, trailed sentences, vocabulary). You must read the **full** audit to earn credit. |
| **Spaced repetition** | Anything you prove re-enters an FSRS review schedule; a forgotten item spawns a fresh gated recall task. |
| **Focus sessions** | A timed work block whose measured duration earns the streak's "timer honored" condition. |
| **Streak** | One server-computed number, with a single grace token per ISO week. |
| **Taste log** | A short, immutable end-of-day judgment. |
| **Glossary** | A searchable ledger of notation and terms, with overloaded-symbol detection. |
| **Weekly synthesis & drift review** | Re-grades a sample of past passes ("grade harshly") to catch verdict drift, then assembles a written synthesis of the week. |
| **Export & audit trail** | Markdown export of the record; every LLM call (including failures) is persisted for inspection. |

## How judging works

The examiner is an LLM served via **NVIDIA NIM**, called at **temperature 0** and
designed to **fail closed**: any evaluation error (unreachable model, unparseable
output, an ambiguous verdict) leaves the task untouched rather than passing or
failing it — an infrastructure glitch can never complete your work or burn your
retry. Submitted answers and artifacts are immutable once recorded, the
one-retry-per-day cap is enforced at the database layer, and untrusted input is
isolated so it cannot inject a verdict.

**Privacy:** your audio never leaves your machine. Recordings are transcribed
**locally** with faster-whisper; only the resulting transcript text and a few
computed statistics are sent to the LLM for the audit.

## Interface

The UI is the **"Evidence File"** — a deliberately serious, specimen-ledger design
rather than a cheerful dashboard: aged-paper exhibit cards, ink-stamped `PASS`/`FAIL`
verdicts, a live-waveform recorder, and a plain-language day-by-day history. It is
meant to read as an instrument of record, not an app that congratulates you.

## Tech stack

- **Backend** — Python · FastAPI · SQLAlchemy · SQLite (WAL, numbered migrations,
  triggers) · faster-whisper (local transcription) · ffmpeg · NVIDIA NIM (evaluation).
- **Frontend** — React 19 · Vite · Tailwind CSS · Framer Motion.

## Getting started (local)

**Prerequisites:** Python 3.11+, Node 18+, and `ffmpeg` on your `PATH`.

```bash
# 0. Secrets — .env is gitignored
cp .env.example .env      # then set NVIDIA_API_KEY (Telegram vars optional)

# 1. Backend setup (one-time)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. Backend (terminal 1)
cd backend && ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Frontend setup (one-time)
cd frontend && npm install

# 4. Frontend (terminal 2)
cd frontend && npm run dev

# 5. Open the app
xdg-open http://localhost:5173
```

The first recording downloads the `small` faster-whisper model (~460 MB) into
`~/.cache/huggingface`; the upload will pause once while it does. Pre-download it
with:

```bash
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

**Optional nightly auto-close** (`crontab -e`):

```
0 23 * * * curl -s -X POST http://127.0.0.1:8000/api/day/close > /dev/null
```

## Tests

The backend ships an anti-gaming and integrity suite (state machine, concurrency,
prompt-injection, timezone, spaced repetition, streak, and a simulated-week
regression):

```bash
.venv/bin/pip install -r backend/requirements-dev.txt   # one-time
cd backend && ../.venv/bin/python -m pytest tests/
```

## Project layout

```
backend/     FastAPI app, SQLAlchemy models, migrations, LLM + transcription
frontend/    React + Vite app (the "Evidence File" UI)
prompts/     LLM prompt templates (question generation, answer/transcript audit, synthesis)
data/        SQLite database + recorded audio  (gitignored)
week.yaml    Hand-edited weekly themes, displayed read-only
```

## Notes

- **Hosting.** Sentinel is designed to run as a **private, single-user** service —
  on your own machine or behind a private network — not as a public site.
- **Timezone.** Day boundaries, streak, and day-close all use the IST civil
  calendar (`Asia/Kolkata`); every stored timestamp is tz-aware UTC.
- **Naming.** The product is **Sentinel**; the backend module and its database
  (`gatekeeper.db`, the `/api` routes) retain the earlier working codename
  "gatekeeper" internally.
