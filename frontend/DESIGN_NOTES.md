# Evidence File — implementation notes

The frontend implements the approved **"Evidence File" (1c)** direction from the
Claude Design export (`Sentinel App.dc.html`). Built in two passes:

- **Phase 1 — static fidelity.** The export's markup + CSS were ported verbatim
  into `src/evidence.css` (the `dk-*` / `s-*` classes and the DC runtime atomics)
  and componentized. All four surfaces (Today fan, Record audit, History archive
  + drill-down, Close-of-day modal) reproduce the export's colors, type
  (Courier Prime + Oswald), spacing, rotation values, shadows and dashed
  dividers. Verified by screenshot against the export.
- **Phase 2 — behavior.** Wired to the existing backend API, following
  `decisions.md` for all logic. No backend/product rules were reinterpreted.

## Component map
`components/`: `ExhibitCard`, `VerdictStamp`, `StreakChip`, `ThemeStrip`,
`TicksStrip`, `EvidenceDoc`, `CloseFileModal`, `GatedFlow`. Screens: `App`
(shell/tabs/close-flow), `Today`, `Record`, `History`. `format.js` holds
presentation-only date/time helpers.

## Backend mapping
- **Exhibit cards** = the day's `gated` tasks (backend caps at 3/day). Stamp ←
  `status` (`passed`→PASS, `failed_once`/`failed_final`→FAIL, `open`→none);
  one-line reason ← `reason`; retry-once-then-locked ← `attempts` +
  `failed_once`→`failed_final`. Clicking an unresolved card opens the gated flow
  (`artifact` → examiner `question` → final `answer` → verdict).
- **Free ticks** = `simple` tasks. Toggle completes via
  `POST /api/tasks/{id}/complete` — one-way (`open→done`), matching the backend;
  a done tick cannot be un-ticked.
- **Exhibit C / Record tab** = the spoken-shadowing recording + LLM audit. The
  read-gate is genuine: MARK AS READ is inert until the report is scrolled to
  its end (or the audit is short enough not to overflow), then
  `POST /api/recordings/{id}/viewed`.
- **Close of day** → `POST /api/day/close`; the modal summary and streak come
  from the real response.
- **Streak / week theme** ← `GET /api/streak`, `GET /api/week` (display only;
  streak is computed server-side at close, never in the client).

## Deviations from the export / product (flagged, not silent)
1. **Wordmark.** Kept the export's literal **"SENTINEL — EVIDENCE FILE"**. The
   product is **Gatekeeper**; this is a one-line change in `App.jsx` once you
   confirm the intended name. Left as-is to honor Phase-1 "reproduce exactly".
2. **Per-card session timer.** The design shows a per-exhibit stopwatch, but the
   backend has no task↔session link. A single work session (backend allows one
   open at a time) is associated to an exhibit **client-side** (localStorage) so
   its live timer shows on that card; duration + `timer_honored` are still
   measured/earned server-side. `planned_minutes` defaults to 20 (the design
   exposes no input). Resolved cards show the real `attempts` count in that slot
   instead of a fabricated duration.
3. **"FILE 192" folio.** No backend day-counter exists, so the header shows the
   live date only; History's FILE column shows `—`.
4. **History SESSION / STREAK columns.** `/api/history` returns no per-day
   session minutes or structured streak, so SESSION shows total recording time
   (else `—`) and STREAK is best-effort parsed from `summary_line` (else `—`).
5. **Per-task requirement line.** No `requirement` field exists; cards show a
   constant "Evidence required · examined on submission · verdict final".
6. **Recording floor.** The export copy says "30 minutes"; the backend enforces
   **4:30** (`MIN_SEC=270`). The UI uses the real floor.
7. **Weekly synthesis.** No synthesis read endpoint exists; the panel reads the
   `## Weekly synthesis` section best-effort from `GET /api/export`, and shows an
   empty-state prompt otherwise.
8. **Ancillary Record.** The export did not depict several wired features
   (spaced-repetition reviews, taste log, task creation). Rather than drop
   working functionality, they live in an "ANCILLARY RECORD" strip below the
   footer on Today, styled to match. `ThemeStrip`'s "WEEK 28 THEME" label is a
   static default (the theme text itself is real).

## Motion
Verdict stamps **strike into place** only when a verdict first resolves during a
session (tracked in `Today`), not on static render of already-resolved cards;
the big FILE CLOSED / gated-flow verdict stamps strike similarly. Screen changes
use one short, deliberate fade. All motion is gated on
`prefers-reduced-motion`.

## Running
Frontend: `npm run dev` (proxies `/api` → `127.0.0.1:8000`). Backend:
`cd backend && ../.venv/bin/uvicorn main:app --port 8000`.
