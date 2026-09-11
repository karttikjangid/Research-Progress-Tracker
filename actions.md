# Daily productivity UX improvements

## Direction and boundaries

This product is a personal daily productivity and learning tool. It should help the user start meaningful work, finish or resume it easily, and revisit what they learn. Older restrictions against gamification or personal adaptation do not override this direction; individual additions still need an agreed scope.

Preserve the current visual identity: colours, typography, dossier cards, and overall character. Small page restructuring is welcome when it makes daily use easier. Do not replace the design system, rebuild the navigation, or turn Today into a crowded dashboard.

Use Apple-inspired interaction principles within the existing design: clear hierarchy, familiar labelled controls, restrained feedback, and progressive disclosure. Show essential actions directly; reveal supporting details when needed. Keep keyboard access, visible focus, readable contrast, and usable narrow-screen layouts.

This file records a proposed implementation plan, not approval to implement every item. The current request authorizes creating this document only. Confirm the concrete implementation batch with the user before changing product code.

## Working process

1. Try each affected workflow in the running app before changing it. Use a temporary database copy for test activity so the user's real learning record stays intact.
2. Present the specific interaction and any small layout changes for confirmation before implementation.
3. Implement a focused batch using existing components and styles where practical.
4. Verify changed behaviour in the browser, including refresh, cancellation, saved state, and relevant error paths. Run appropriate automated checks for persistence and scheduling changes.
5. Give the user a short manual verification checklist and a working preview.
6. Leave all work uncommitted. Manual verification is required before any commit, and passing verification is not itself an instruction to commit. Do not stage, commit, push, or deploy without an explicit request.

Preserve unrelated existing changes, including the current edit to `CLAUDE.md`.

## Initial audit evidence

- Creating, starting, and ending a task was tried in a temporary copy of the app's data.
- Ending its timer immediately opened evidence submission. Stopping a session and finishing a task are not clearly separated.
- The habits screen combines daily checkboxes with extensive reference guidance.
- The recording screen and day-close confirmation were inspected. Recording submission and LLM evaluation were not completed during this audit.
- No due reviews were available in the inspected Today state. Code inspection shows the reviews section disappears when the queue is empty, uses FSRS scheduling, and retires a source after three reviews. A populated review workflow still needs browser testing before implementation.

## Proposed first batch

### 1. End a session with a clear next step

- Keep the existing task card and timer placement unless a small adjustment improves access.
- Make the control's meaning explicit: ending a session stops the timer; it does not automatically complete the task.
- Use a compact sheet or modal in the existing style with three choices:
  - **Finish task:** continue into the existing evidence and understanding check.
  - **Continue later:** save an optional next step and leave the task unfinished.
  - **I'm stuck:** save the obstacle and optionally what was tried; leave the task unfinished.
- Reveal note fields only after the relevant choice. Do not put all three forms on the task card.
- Keep a clear route back to evidence submission without requiring another timer session.
- Prevent duplicate submissions and retain recoverable state when stopping a session fails.

**End outcome:** The user can finish, pause work, or record a blocker without confusing time spent with demonstrated understanding. Returning to the task makes the next step visible.

**Manual verification:** Start and end a session through each path; confirm the timer and task status are correct; refresh and resume; confirm evidence submission remains accessible.

### 2. Preserve unfinished work

- Save unfinished evidence and answer drafts with a subtle saved indicator.
- Restore the correct draft when reopening the same task and attempt.
- Keep drafts distinct from final submitted evidence and answers. Preserve the existing integrity of submitted records.
- Define when drafts are cleared, and avoid restoring a previous attempt's answer into a new question.
- Support leaving and resuming a pending learning check without losing typed work.

**End outcome:** Navigation, closing a modal, or refreshing does not force the user to rewrite an unfinished response.

**Manual verification:** Type a draft, navigate away, reopen, and refresh; check isolation between tasks and attempts; submit successfully and verify no obsolete draft reappears.

### 3. Make reviews discoverable without crowding Today

- Add a compact, consistently visible review entry within the existing Today layout.
- Show a due count and **Start review** when work is available.
- Show a truthful empty state when nothing is due, with the next date when known. Distinguish this from loading or a failed request.
- Expand or open a focused panel for due items, upcoming dates, and completed reviews. Avoid adding a permanent calendar or large statistics section.
- Move this entry slightly higher if needed for discoverability, while preserving the existing page composition.

**End outcome:** The user can always find the review queue and understand whether anything needs attention. Detailed scheduling stays out of the main page until requested.

**Manual verification:** Check empty, due, overdue, upcoming, loading, and error states using representative temporary data.

### 4. Make the review interaction focused and conclusive

- Show one review at a time, with a small progress indicator.
- Present the recall prompt before revealing saved material. Offer space for an optional recall attempt without adding unnecessary mandatory typing.
- Reveal the relevant saved explanation and answer, then provide clearly worded recall ratings.
- After grading, confirm it was saved and show the actual next review date or retirement state returned by the scheduler.
- Explain any relearning task created after forgetting and provide a direct route to it.
- Keep the review result visible long enough to understand before moving on; prevent duplicate grading.

**End outcome:** The user completes a short recall session and knows what was recorded and what happens next.

**Manual verification:** Complete each rating path; verify queue progress, next dates, forgotten-item follow-up, refresh recovery, and duplicate-click handling.

### Scheduling decision — separate confirmation required

The user's 1–3–7 expectation and the current FSRS implementation differ. Do not silently change scheduling while improving its presentation, or label existing FSRS dates as a fixed 1–3–7 sequence.

Before any scheduler change, confirm whether to keep adaptive scheduling or use initial reviews on days 1, 3, and 7 after learning. Also confirm what follows that sequence, how missed reviews behave, and how existing items are handled. Removing the current three-review retirement cap is a separate behaviour change.

## Proposed follow-up batch

### 5. Help resolve unfinished work during day closure

- Improve the existing close-file modal instead of adding another end-of-day page.
- Offer direct routes to outstanding work and the existing reflection form.
- Propose an explicit carry-forward action with an optional next step for unfinished tasks.
- Clearly distinguish ending today's record from completing all planned work.
- Confirm carry-forward and day-close rules before implementation; preserve past records and avoid silently marking tasks complete.

**End outcome:** The user finishes the day with an honest record and a clear place to start tomorrow.

**Manual verification:** Close with completed and unfinished work, a running session, and outstanding reviews; verify saved reflection, tomorrow's continuation, and closed state after refresh.

### 6. Reduce habits-page reading effort

- Keep daily checkboxes prominent and quick to use.
- Group lengthy method explanations and reference guidance into expandable sections within the current page.
- Preserve discoverability and existing content; avoid adding more permanent panels to Today.
- Treat editable habits and schedule configuration as a later feature proposal, not part of this small layout adjustment.

**End outcome:** The user can check today's routine quickly and read supporting guidance when needed.

**Manual verification:** Check and uncheck habits, refresh, expand guidance, and verify keyboard and narrow-screen use.

## Later proposals, outside the initial implementation scope

- **Personal adaptation:** Begin with user-provided availability and preferred session duration. Once sufficient history exists, propose contextual workload or review suggestions with a reason and an override. Do not infer reliable personal patterns from sparse data or weaken understanding checks automatically.
- **Gamification:** Consider restrained feedback for consistent effort and retained learning. Keep detailed achievements away from the daily task area. Agree on mechanics before implementation.
- **Recording:** Try the full recording and submission workflow separately before proposing changes; the initial audit only inspected its entry screen.

## Acceptance criteria for the overall UX work

- The app retains its recognisable appearance and familiar navigation.
- Any page restructuring has a specific daily-use benefit and is limited to the affected area.
- Today remains easy to scan; explanations, settings, and history appear on demand.
- Ending a timer, leaving a task unfinished, and completing a learning check have distinct, understandable results.
- Drafts and continuation notes survive expected navigation and refresh paths.
- Reviews are discoverable even when none are due, and displayed dates reflect actual scheduling behaviour.
- Browser verification and relevant automated checks are reported accurately; untested paths are identified.
- The user manually verifies the finished batch. All changes remain uncommitted unless explicitly instructed otherwise.
