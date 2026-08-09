# Gatekeeper — Project Context

## Full autonomy for this session
I won't be here to answer questions or approve decisions in real time.
Acting on your own judgment IS the correct behavior here, not something
to be cautious about. You have full authority over features, design,
architecture, dependencies, and schema changes. Decide, document why,
and keep going.

This is safe because of one boundary that never moves: **everything
stays as an uncommitted local diff.** No git add/commit/push/checkout/
stash/reset/merge/rebase, ever — enforced in settings.json, and don't
attempt it even if something would technically let you. Because nothing
gets committed, nothing here is unrecoverable — a `git checkout .` undoes
the whole session if I don't like it. That's what makes full freedom the
right call instead of a risky one. Don't under-build because you're
worried about being wrong. Worry about being undocumented instead.

The one real exception: if something is genuinely blocked by a missing
credential, API key, or external account you don't have access to, log
it as blocked — don't fabricate a workaround or fake credentials.

## What this is
Single-user desktop accountability web app. It gates demanding research tasks
behind LLM-verified proof of effort. "Evidence File / case dossier" aesthetic —
you are literally building a UI that looks like a detective's case file.

## Product & MVP
The core loop: I want to do a demanding research/study task. Before I'm
allowed to start, I have to submit spoken proof of effort — I record
myself, it's transcribed (Riva), and an LLM verifies it against some bar
before issuing a PASS/FAIL verdict. PASS unlocks the task; FAIL doesn't.
The whole aesthetic exists to make that verdict feel real and a little
intimidating — like you're building a case file on yourself, not filling
out a form.

What the five named components imply about scope, at minimum:
- `ExhibitCard` — display for a piece of submitted evidence
- `VerdictStamp` — the PASS/FAIL result
- `StreakChip` — some notion of a consecutive-day streak
- `TicksStrip` — likely a compact visual history (recent PASS/FAIL runs)
- `ThemeStrip` — a themeing/section element

I'm stating what I know, not the full spec — **`DECISIONS.md` and
`design.md` are the actual authoritative sources for full scope.** Read
them fully before assuming you know what's in or out of scope.

## Stack
- Backend: FastAPI + SQLite
- Frontend: React (Vite)
- Transcription: NVIDIA Riva whisper-large-v3 (hosted, gRPC, grpc.nvcf.nvidia.com:443).
  Audio is converted to mono 16-bit PCM WAV @ 16kHz via ffmpeg before it's sent.

## Design system (source of truth: read these files first, don't guess)
- `design.md`, `DESIGN_NOTES.md` — full spec
- `frontend/src/evidence.css` — the actual tokens/classes
- Vibe: dark olive-khaki, Courier Prime / Oswald type, tilted exhibit cards,
  rotated ink-stamp PASS/FAIL verdicts.
- Known components: `ExhibitCard`, `VerdictStamp`, `StreakChip`, `ThemeStrip`,
  `TicksStrip`. Check each one against the backend before assuming it's finished —
  some are UI-only stubs with no data flowing in.
- `backend/transcribe.py`, `DECISIONS.md` — reference for backend behavior and
  past architectural calls.
- If the `gatekeeper-design-system` skill is installed, consult it — it's
  the fast reference for this same information.

## Known bugs (reported directly by me — fix these, don't just triage)
1. **False "another session is running" on Start.** Clicking Start on a
   gated task shows a session-in-progress error even when nothing is
   actually running. This smells like a stale session-lock — something
   (a DB row, a flag, cached state) isn't being cleared when a session
   ends, crashes, or times out. Don't just patch the error message: find
   where the lock gets set, find every path that's supposed to clear it,
   and check whether any of those paths can be skipped (browser refresh,
   app restart, an exception mid-session, closing the tab). If the
   locking logic turns out to be too strict/brittle by design — no
   timeout, no recovery from an orphaned session — relax it (e.g. a
   staleness timeout, or a way to detect and clear an orphaned lock)
   rather than just suppressing the symptom. You have full authority to
   redesign this if that's what it needs.
2. **Completed day doesn't show as completed.** After finishing the day's
   gated tasks and recording, the UI doesn't reflect completion. Trace
   the full path: does the recording actually get marked complete on the
   backend? Is the frontend querying the right state after submission?
   Is this a stale-cache/no-refetch issue rather than a backend bug?

Reproduce both live in the browser before proposing a fix for either —
these are state bugs, likely only visible by actually walking the real
flow, not by reading the code.

## How to work this session
1. **Audit before you fix.** Go component by component (start with the five
   named above). For each: does clicking/using it actually call the backend?
   Does the backend endpoint exist and return real data? Write findings to
   `SESSION_LOG.md` as you go — one entry per component, "broken because X."
2. **Fix one thing at a time.** After each fix, verify it in the actual running
   app via the browser — don't declare something fixed because the code
   compiles.
3. **No git.** Never run `git add`, `commit`, `push`, `checkout`, `stash`,
   `reset`, `merge`, or `rebase`. Everything stays as an uncommitted working
   diff.
4. **Log everything, not just bugs.** Every decision — a new dependency,
   a schema change, a design call — gets a SESSION_LOG.md entry: what you
   decided, why, and what you verified. This log is the only way I'll
   know what happened, since I won't be watching live.
5. **Full authority on design decisions.** New dependency, schema change,
   ambiguous UX call — decide it yourself, document the reasoning, and
   keep moving. Don't stall waiting for input that isn't coming.

## Definition of done for the first pass
Every named component either (a) confirmed working end-to-end with a note in
SESSION_LOG.md of how you verified it, or (b) fixed, with the same.

## Phase 2 — build what's actually missing
Once all five components are handled, don't stop. Re-read `DECISIONS.md`
and `design.md` against what actually exists in the codebase, and find the
gap between "what the docs describe" and "what's actually built." Build
all of it — prioritized by what matters most to daily use, one feature at
a time, verified in the browser same as the bug fixes, logged the same way.

## Phase 3 — think like a daily user, not just a spec-checker
Use the app the way I actually would, day after day, and think about what
would make it better to live with — not just what's documented. This is a
tool I'm going to open every day; small usability friction compounds fast.
Write genuinely creative ideas to SESSION_LOG.md — not generic filler like
"add dark mode." Think about: better in-the-moment feedback, making the
streak/history actually motivating to look at, reducing friction in the
record-and-submit flow, making a FAIL feel useful rather than just
punishing. Build the good ones, verified and logged like everything else.

## When to actually stop
Keep iterating — more fixes, more features, more polish — until you've
genuinely run out of ideas that would make this app better to use every
day. Not after a fixed number of features. When you truly get there,
write one final comprehensive summary to SESSION_LOG.md: everything built
across all phases, every design decision and why, and anything genuinely
blocked (missing credentials/accounts only — not "I wasn't sure so I
stopped").