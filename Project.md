# PROJECT_CONTEXT.md — "Gatekeeper" (accountability web app)

Single source of truth for Claude Code. Read fully before writing any code.

## What this is

A local-only web app that gates my daily to-do list behind proof of learning.
It is an enforcement instrument, not a product. Owner: Kartik (solo user, localhost).

**Hard constraint: the MVP must be functional in ONE working day.** Anything not in
"MVP scope" below is forbidden until further notice. If a feature idea is tempting,
add a line to `ICEBOX.md` and move on.

## Product rules (non-negotiable — encode these, do not soften them)

1. **Two task types.** `simple` tasks check off freely. `gated` tasks (max 3/day)
   can only be marked done through an evaluation flow. The friction lives ONLY on
   gated tasks.
2. **Gated learning task flow:** user clicks "complete" → must paste/type their
   artifact (proof text, code diff, decode notes — NOT a topic name) → backend sends
   artifact to the LLM evaluator → evaluator generates ONE probing question derived
   from the artifact itself → user answers in a textarea (no edit after submit) →
   evaluator returns PASS/FAIL + one-line reason. FAIL = task stays open, one retry
   allowed per day with a NEW question. No override button. No "mark done anyway."
3. **Evaluator must be harsh.** System prompts are in `prompts/` (provided below).
   The evaluator FAILS generic-but-correct summaries. It demands a specific step,
   an edge case, or a "what breaks if X" answer. Temperature 0.
4. **Verbal drill flow:** browser records ≥5 min of mic audio (MediaRecorder) →
   upload → local transcription → LLM audits transcript (filler density, sentences
   that die midway, imprecise/wrong technical vocabulary) → the day's verbal task
   unlocks ONLY after the user opens and scrolls the audit report. Store audio +
   transcript + audit by date. A recording under 4:30 is rejected client-side AND
   server-side.
5. **Accountability ping:** on day close (or 23:00 cron), POST a one-line summary
   ("Jul 12: 3/3 gated passed, verbal done") to a Telegram bot chat ID from `.env`.
   If unset, write the line to `public_log.md` instead. This feature is tiny but
   mandatory — it is the only real teeth the system has.
6. **Weekly plan is data, daily plan is user input.** `week.yaml` (hand-edited)
   lists the week's themes. The app displays it read-only; the user creates each
   day's tasks in the UI each morning. The app never auto-generates tasks.

## Tech stack (decided — do not substitute)

- **Backend:** Python 3.11+, FastAPI, SQLite via SQLAlchemy, uvicorn. One process.
- **Frontend:** React + Vite + Tailwind. Plain fetch, no state library. One page
  with three panels (Today / Record / History). No router if avoidable.
- **Transcription:** `faster-whisper`, model `small`, int8. Must run on CPU if CUDA
  is unavailable (dev machine is a GTX 1650 4GB — small/int8 fits; fall back to
  `base` if VRAM errors occur).
- **LLM Engine (Nvidia NIM API)**: 
  - Base URL: `https://integrate.api.nvidia.com/v1`
  - Model from `.env` (`EVAL_MODEL`, default: `meta/llama-3.1-70b-instruct`).
  - Key from `.env` (`NVIDIA_API_KEY`).
  - Never hardcode, never log the key. `.env` in `.gitignore` from the first commit.
- **Audio:** MediaRecorder → webm/opus upload → stored under `data/audio/YYYY-MM-DD/`.
- No Docker, no auth, no HTTPS, no deployment config. Localhost only.

## Data model (SQLite)

- `tasks(id, date, title, type[simple|gated], status[open|passed|failed_once|done],
  artifact TEXT, question TEXT, answer TEXT, verdict TEXT, reason TEXT)`
- `recordings(id, date, duration_sec, audio_path, transcript_path, audit_path,
  audit_viewed BOOL)`
- `day_log(date, summary_line, pinged BOOL)`

## API surface (keep to exactly this)

- `GET/POST /api/tasks?date=` — list/create tasks
- `POST /api/tasks/{id}/complete` — simple tasks only
- `POST /api/tasks/{id}/artifact` — submit artifact → returns generated question
- `POST /api/tasks/{id}/answer` — submit answer → returns verdict + reason
- `POST /api/recordings` — multipart upload → kicks transcription+audit (sync is
  fine; show a spinner) → returns audit
- `POST /api/recordings/{id}/viewed` — marks audit read, unlocks verbal task
- `POST /api/day/close` — builds summary line, sends ping
- `GET /api/week` — serves parsed week.yaml

## Evaluator prompts (create these files verbatim, then refine only wording)

`prompts/question_gen.txt`
> You are a harsh ETH-style TA. You receive a student's work artifact (proof,
> derivation, code diff, or decode notes). Generate exactly ONE probing question
> answerable only by someone who actually did and understood this work. Prefer:
> a specific step's justification, an edge case (n=1, singular matrix, heavy tail,
> measure-zero event), or "what breaks if <assumption> is removed". Never ask a
> question answerable from the topic name alone. Output only the question.

`prompts/answer_eval.txt`
> You are a harsh ETH-style TA. Given the artifact, the question, and the student's
> answer, output verdict PASS or FAIL plus one sentence of reason. FAIL if the
> answer is generic, restates the question, hedges without committing, or misuses
> a technical term (e.g. "consistent" for "unbiased" — flag vocabulary misuse
> explicitly). PASS requires a specific, correct, committed claim. When in doubt,
> FAIL. Output format: `VERDICT: PASS|FAIL — <reason>`.

`prompts/transcript_audit.txt`
> Audit this transcript of a 5-minute technical monologue. Report, with counts and
> quoted examples: (1) filler density per minute (um, like, basically, you know),
> (2) sentences that died midway or were restarted, (3) imprecise or incorrect
> technical vocabulary with the term the speaker likely meant, (4) altitude check:
> did the explanation ever state WHY, or only WHAT? End with the single highest-
> leverage fix for tomorrow's recording. Be blunt. No praise padding.

## MVP scope for day one (in build order)

1. Backend skeleton + DB + task CRUD + simple-task completion
2. Gated flow (artifact → question → answer → verdict) end to end
3. Frontend Today panel wired to the above
4. Recording panel: record, upload, transcribe, audit, viewed-gate
5. Day close + Telegram/public_log ping
6. `week.yaml` display

If time runs out, ship at whatever step is complete. Steps 1–3 alone are a usable v1.

## Explicitly OUT of scope (do not build, do not suggest)

Charts, dashboards, auth, user accounts, dark-mode toggles, mobile layout polish,
calendar sync, Docker packaging, editing past days, deleting recordings, any second
page that isn't History.

**Re-ratified 2026-07-11 (owner):** spaced-repetition scheduling (FSRS, self-graded)
and a single server-computed quality streak are now IN scope — moved out of this
list. The general ban on *gamification* still holds: the streak is display-only, one
number, computed server-side; no badges, levels, points, or flashy UI. See
decisions.md "2026-07-11 spaced-repetition + streak session".

## Rules for Claude Code in this repo

- Never run `git add/commit/push` — the owner handles all git operations manually.
- simplify the step, don't grow the budget.
- Write `plan.md` before coding; keep a running `todo.md`; note irreversible
  decisions in `decisions.md`.
- On any ambiguity, choose the simpler option and log it in `decisions.md` —
  do not ask, do not block.