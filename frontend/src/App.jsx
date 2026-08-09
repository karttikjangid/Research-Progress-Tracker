import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get, post } from './api'
import { headerDate } from './format'
import Today from './Today'
import Record from './Record'
import History from './History'
import Roadmap from './Roadmap'
import Habits from './Habits'
import CloseFileModal from './components/CloseFileModal'

const SCREENS = { today: Today, record: Record, history: History, roadmap: Roadmap, habits: Habits }
const TABS = [['today', 'TODAY'], ['record', 'RECORD'], ['history', 'HISTORY'], ['roadmap', 'ROADMAP'], ['habits', 'HABITS']]

// PHASE 2 — the Evidence File shell, wired. Week theme and streak come from the
// backend; CLOSE THE FILE runs the real day-close. Wordmark renamed from the
// export's literal "SENTINEL" to the actual product name (see DESIGN_NOTES.md
// deviation #1 — this was flagged as a one-line change pending confirmation;
// decided here since every other doc calls the product Gatekeeper).
export default function App() {
  const [screen, setScreen] = useState('today')
  const [streak, setStreak] = useState(null)
  const [closed, setClosed] = useState(false)
  const [modal, setModal] = useState(false)

  // closed_today is backend truth (today's day_log row exists) — without
  // this, `closed` only ever flipped true from a live confirm-close click in
  // this same session and reverted to false on every reload, even though the
  // day was genuinely already closed.
  const loadStreak = useCallback(() => {
    get('/api/streak').then((d) => { setStreak(d); setClosed(!!d.closed_today) }).catch(() => setStreak(null))
  }, [])
  useEffect(() => { loadStreak() }, [loadStreak, screen])

  const Active = SCREENS[screen]

  return (
    <>
    <div className="s-margin-col left" aria-hidden="true"><span>Positive mind</span></div>
    <div className="s-margin-col right" aria-hidden="true"><span>If you can dream it you can do it</span></div>
    <div className="s-app">
      <div className="fx jb ac">
        <div className="dk-osw fs14">GATEKEEPER — EVIDENCE FILE</div>
        <div className="s-tabs">
          {TABS.map(([key, label]) => (
            <button key={key} className={`s-tab${screen === key ? ' on' : ''}`}
              onClick={() => setScreen(key)} type="button">{label}</button>
          ))}
        </div>
        <div className="fx ac gap16">
          <span className="fs13" style={{ opacity: .6 }}>{headerDate()}</span>
          {closed
            ? <span className="dk-osw fs12" style={{ color: '#d9a49e' }}>FILE CLOSED</span>
            : <button className="s-btn s-btn-lt" onClick={() => setModal(true)} type="button">CLOSE THE FILE</button>}
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div key={screen}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
          transition={{ duration: .2, ease: 'easeOut' }}>
          <Active closed={closed} streak={streak} onStreakChange={loadStreak} />
        </motion.div>
      </AnimatePresence>

      <AnimatePresence>
        {modal && (
          <CloseFileController key="closefile"
            closed={closed}
            onClosed={() => { setClosed(true); loadStreak() }}
            onDismiss={() => setModal(false)}
          />
        )}
      </AnimatePresence>
    </div>
    </>
  )
}

// Loads today's tasks to build the close-of-day summary, then runs the real
// POST /api/day/close. Two states: confirm (with the verdict summary + real
// consequence) and the closed acknowledgement.
function CloseFileController({ closed, onClosed, onDismiss }) {
  const [tasks, setTasks] = useState(null)
  const [result, setResult] = useState(null) // day/close response
  const [err, setErr] = useState('')
  const [openSession, setOpenSession] = useState(null)
  const [tastelog, setTastelog] = useState(undefined) // undefined=loading, null=none

  useEffect(() => { get('/api/tasks').then(setTasks).catch((e) => setErr(e.message)) }, [])
  // A session left running through close() never gets an ended_at today, so
  // it can't count toward timer_honored — closing is final and never
  // retroactively fixed once the streak snapshot is taken. Surfaced here so
  // it isn't a silent, easy-to-miss way to lose a streak day.
  useEffect(() => { get('/api/sessions/current').then(setOpenSession).catch(() => {}) }, [])
  // The end-of-day consolidation (tastelog) — null when none written yet. Only
  // a missing-warning trigger when the day actually had a session, matching the
  // backend's own TASTELOG-MISSING rule (_close_line, main.py).
  useEffect(() => { get('/api/tastelog').then(setTastelog).catch(() => setTastelog(null)) }, [])

  const gated = (tasks?.tasks || []).filter((t) => t.type === 'gated')
  const ticksDone = (tasks?.tasks || []).filter((t) => t.type === 'simple' && t.status === 'done').length
  const ticksTotal = (tasks?.tasks || []).filter((t) => t.type === 'simple').length
  const broken = gated.some((t) => t.status === 'failed_final')

  const VMAP = {
    passed: { verdict: 'PASS', tone: 'dk-p' },
    failed_final: { verdict: 'FAIL', tone: 'dk-f' },
    failed_once: { verdict: 'FAIL (RETRY LEFT)', tone: 'dk-f' },
    open: { verdict: 'OPEN — FILED AS-IS', tone: '' },
  }
  const rows = gated.map((t, i) => ({
    label: `EXHIBIT ${String.fromCharCode(65 + i)} — ${t.title}`,
    ...(VMAP[t.status] || { verdict: t.status.toUpperCase(), tone: '' }),
  }))

  const streakNum = result?.current_streak
  const consequence = broken
    ? `A gated exhibit stands at FAIL. Closing the file records today as BROKEN${streakNum != null ? '' : ' and returns the streak to nought'}. Closing is deliberate and final — the examiner does not reopen files.`
    : 'Closing files today’s record and pings the log. Open exhibits are filed as-is. Closing is deliberate and final — the examiner does not reopen files.'
  // Close-time warnings, coldest-consequence first: a running session can cost
  // a streak day (unrecoverable once closed); the others make the filed record
  // read incomplete. Wording mirrors the exact flags the day's own summary line
  // uses ("verbal MISSED", "TASTELOG MISSING") so the warning and the result
  // speak the same language.
  const verbal = tasks?.verbal
  const warnings = [
    openSession &&
      `A ${openSession.kind.replace('_', ' ')} session is still running. It won't count toward today's honored-timer condition unless you end it before closing.`,
    verbal && !verbal.recorded &&
      'No verbal drill on record today. The file will read verbal MISSED.',
    verbal && verbal.recorded && !verbal.done &&
      "The verbal drill's audit is unread. Until it's read, the file reads verbal MISSED.",
    tasks?.had_session_today && tastelog === null &&
      'No end-of-day consolidation is written. The file will read TASTELOG MISSING.',
  ].filter(Boolean)

  const closedNote = result
    ? `${result.summary_line}<br>${result.already_closed ? 'Already closed earlier today.' : (result.pinged ? 'Filed and pinged.' : 'Filed to the local log.')} The ledger reopens at 00:00.`
    : 'The ledger reopens at 00:00.'

  const confirmClose = () => {
    post('/api/day/close').then((r) => { setResult(r); onClosed() }).catch((e) => setErr(e.message))
  }

  return (
    <CloseFileModal
      closed={closed || !!result}
      loading={!tasks && !err}
      error={err}
      rows={rows}
      tickCount={ticksDone}
      tickTotal={ticksTotal}
      warnings={warnings}
      consequence={consequence}
      closedNote={closedNote}
      onKeepWorking={onDismiss}
      onConfirmClose={confirmClose}
      onDone={onDismiss}
    />
  )
}
