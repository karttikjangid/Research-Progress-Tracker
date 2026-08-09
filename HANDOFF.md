# Gatekeeper — Session Handoff

**Session date:** 2026-08-06 · **Branch:** `main` · **Nothing committed** — the
whole session is an uncommitted working diff, per CLAUDE.md. `git checkout .`
undoes all of it.

Full blow-by-blow (root causes, verification evidence, reasoning for every
decision) lives in **`SESSION_LOG.md`**. This file is the short version plus
the concrete spec for the three items still to build.

---

## Part 1 — What was done this session

### Environment (do this first in a new session)

There was no `.venv`. System python is 3.9 but `fsrs>=4.0.0` needs ≥3.10.

```bash
/opt/homebrew/bin/python3.11 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd frontend && npm install
```

Run both servers:

```bash
cd backend && ../.venv/bin/uvicorn main:app --port 8000 --reload
```

```bash
cd frontend && npm run dev
```

Tests (all 106 pass): `cd backend && ../.venv/bin/python -m pytest tests/ -q`

### Bugs fixed (both reproduced live in the browser first)

| Bug | Root cause | Fix |
|---|---|---|
| False "another session is running" | `Today.jsx` treated `localStorage['gk_session']` as the only truth. It's cleared **only** by a clean `endSession()` — so a server restart, crash, or the backend's own >6h auto-close left a permanent false lock with no recovery path. | Added `GET /api/sessions/current` (`backend/main.py`); `Today.jsx` reconciles against it on mount; added an orphan-session banner for sessions whose card left the fan. |
| Completed day didn't show as complete | `closed` in `App.jsx` was pure React state, set only by living through a confirm-close click. Every reload reset it to `false`. | `GET /api/streak` now also returns `closed_today`; `App.jsx`'s `loadStreak()` derives `closed` from it. |

### Component audit — all five are real, no stubs

`ExhibitCard`, `VerdictStamp`, `StreakChip`, `ThemeStrip`, `TicksStrip` were
each driven live against the real backend (including real NVIDIA NIM calls —
a genuine PASS and a genuine FAIL were produced). DESIGN_NOTES.md's claim
that they're all wired holds up. The two bugs above were state-reconciliation
gaps *around* these components, not missing wiring.

### Pre-existing test bugs found and fixed (test-only, no app code)

1. `test_simulated_week_export` never froze the clock despite its own comments
   assuming "today is the 11th" — it only ever passed by being run near
   2026-07-11. `llm._record` stamps `llm_calls` rows with real wall-clock time.
2. `test_spaced_repetition.py`'s local `freeze()` didn't patch
   `clock.now_utc` — the function `llm._record` actually calls.
3. Consolidating `freeze()` into `conftest.py` initially leaked across tests
   because `clock` wasn't in the force-reimport `MODS` list. Added it.

### Features shipped (Phase 2 + 3)

- **Wordmark** `SENTINEL` → `GATEKEEPER` (`App.jsx`) — DESIGN_NOTES.md
  deviation #1, was awaiting confirmation; `index.html`'s `<title>` already
  said Gatekeeper.
- **Live 4:30-floor countdown while recording** (`Record.jsx`) — you used to
  only learn a take was too short *after* losing the minutes.
- **Previous FAIL reason shown on retry** (`components/GatedFlow.jsx`) — the
  retry modal covered the card showing why you failed.
- **Open-session warning before day close** (`App.jsx`,
  `components/CloseFileModal.jsx`) — a session left running can't count toward
  `timer_honored`, and closing is irreversible.
- **The Docket** (`Today.jsx`) — the roadmap's overdue tickets, overdue-first,
  filable as a gated exhibit in one click, with each ticket's real standard of
  proof expandable inline. Closes the loop where the roadmap knew what was due
  but Today made you retype it by hand every morning.
- **Streak checklist** ("what today still needs") — `GET /api/streak/today`
  (`backend/main.py`, above `_opt`) returns the three streak conditions
  evaluated provisionally for today, plus whether this ISO week's grace token
  is unspent. Read-only and **deliberately non-persisting** — decisions.md says
  the streak is computed only at day-close, and writing a `day_log` row here
  would make `_catch_up` skip the day. `StreakConditions` in `Today.jsx`
  renders it as three states, not two: met `[×]`, still fixable today `[ ]`,
  and already settled `[—]` (a twice-failed exhibit can't be un-failed, so
  showing it as a to-do would be a lie). Verified live: correctly showed the
  unmet timer and overdue review as still-reachable, with "No exhibit failed
  twice" met. The `[—]` settled branch was **not** exercised in the browser —
  it needs a `failed_final` task, which costs two real LLM fail cycles.

### Known verification gaps

- The Browser pane blocks microphone access, so the recording **countdown** was
  verified by reading its arithmetic + confirming the mic-denied path still
  renders correctly, not by watching it tick.
- The streak checklist's `[—] settled` branch wasn't exercised (needs a
  `failed_final` task).
- **Stray test row:** task id 4, "Verify failed_final settled state", is left
  `open` with a pending question on 2026-08-09 — I was driving it to
  `failed_final` when the session was stopped. There is no delete-task endpoint
  by design; it will simply be filed as-is at day close. Ignore or answer it.

Everything else this session was verified by real clicks and screenshots.

---

## Part 2 — The two things still to build

Both are **surfacing data the backend already computes** — that's deliberate:
best value-to-risk ratio, no schema churn.

### 1. Vocabulary ledger UI

**Problem.** Every time the examiner catches imprecise vocabulary it writes a
`vocab_flags` row (`term_used`, `term_meant`, `date`, `source`). decisions.md
calls this "a compounding personal error profile." It is injected into future
prompts and printed in the export markdown — but **there is no UI for it
anywhere in the app.** This is the most direct answer to CLAUDE.md's "make a
FAIL feel useful rather than just punishing": your own recurring imprecision,
visible and accumulating.

**Build.**
- Backend: `GET /api/vocab` — flags newest-first. Group by
  `(term_used, term_meant)` with a count so repeats are obvious; a term flagged
  five times is the signal, a one-off is noise. Harvest point is
  `llm._record()` (`backend/llm.py:70`); table is migration `006`.
- Frontend: a panel on **History**, beside the existing Glossary (they're the
  same family — Glossary is notation you've decoded, this is notation you keep
  getting wrong). Sort by count desc. Show `used → meant`, the count, and the
  most recent date.

### 2. Close-of-day warnings

**Problem.** Closing is irreversible ("the examiner does not reopen files") and
the confirm modal lists only exhibits and free ticks. Meanwhile the day's own
summary line already flags `verbal MISSED` and `TASTELOG MISSING` — the app
knows, and says nothing at the one moment it matters.

**Build.**
- `CloseFileModal` already takes a `sessionWarning` string (added this session
  for the open-session case). **Generalise it to a `warnings: string[]`** and
  render each; that keeps one mechanism instead of three parallel props.
- Warnings to add:
  - verbal drill not recorded, or recorded but audit unread —
    `GET /api/tasks` returns `verbal: {recorded, done}`
  - no end-of-day consolidation written — `GET /api/tastelog` returns the row
    or JSON `null`. Match the backend's own rule: `_close_line()`
    (main.py:1075) only flags this when the day has ≥1 session.
- Wording should match the existing voice: factual and cold, not nagging.

---

## Part 3 — Prompt to run in a fresh session

Paste this as the first message of a new session:

```
Read HANDOFF.md at the repo root first, then SESSION_LOG.md for full detail.

Follow CLAUDE.md: you have full autonomy, I won't be answering questions,
and NOTHING gets committed — no git add/commit/push/checkout/stash/reset.
Everything stays an uncommitted working diff.

Set up the environment and start both dev servers as described in HANDOFF.md
Part 1, then confirm the app loads in the browser before changing anything.

Then build the two items in HANDOFF.md Part 2, in order:
  1. Vocabulary ledger UI
  2. Close-of-day warnings

For each one: build it, verify it by actually clicking through the running
app in the browser (not by checking that it compiles), run the backend test
suite to confirm all 106 still pass, and append an entry to SESSION_LOG.md
saying what you built, every design decision and why, and exactly how you
verified it. If something can't be verified in the browser, say so in the log
rather than skipping the check.

Make any design calls yourself and document them. Don't stop to ask.

When both are done, keep going: use the app like a daily user and build
whatever else would genuinely make it better to live with. Stop only when you
run out of high-value ideas, then write a final summary to SESSION_LOG.md.
```
