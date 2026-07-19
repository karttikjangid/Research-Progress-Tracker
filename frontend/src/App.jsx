import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get, post } from './api'
import { headerDate } from './format'
import Today from './Today'
import Record from './Record'
import History from './History'
import Roadmap from './Roadmap'
import Protocol from './Protocol'
import CloseFileModal from './components/CloseFileModal'

const SCREENS = { today: Today, record: Record, history: History, roadmap: Roadmap, protocol: Protocol }
const TABS = [['today', 'TODAY'], ['record', 'RECORD'], ['history', 'HISTORY'], ['roadmap', 'ROADMAP'], ['protocol', 'PROTOCOL']]

// PHASE 2 — the Evidence File shell, wired. Week theme and streak come from the
// backend; CLOSE THE FILE runs the real day-close. The wordmark keeps the
// export's "SENTINEL" (see DEVIATIONS in the handoff note — the product is
// Gatekeeper; renaming is a one-line change once confirmed).
export default function App() {
  const [screen, setScreen] = useState('today')
  const [week, setWeek] = useState(null)
  const [streak, setStreak] = useState(null)
  const [closed, setClosed] = useState(false)
  const [modal, setModal] = useState(false)

  const loadStreak = useCallback(() => {
    get('/api/streak').then(setStreak).catch(() => setStreak(null))
  }, [])
  useEffect(() => { get('/api/week').then(setWeek).catch(() => setWeek(null)) }, [])
  useEffect(() => { loadStreak() }, [loadStreak, screen])

  const Active = SCREENS[screen]
  const theme = week?.themes?.[0] || ''

  return (
    <>
    <div className="s-margin-col left" aria-hidden="true"><span>Positive mind</span></div>
    <div className="s-margin-col right" aria-hidden="true"><span>If you can dream it you can do it</span></div>
    <div className="s-app">
      <div className="fx jb ac">
        <div className="dk-osw fs14">SENTINEL — EVIDENCE FILE</div>
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
          <Active closed={closed} streak={streak} theme={theme} onStreakChange={loadStreak} />
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

  useEffect(() => { get('/api/tasks').then(setTasks).catch((e) => setErr(e.message)) }, [])

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
      consequence={consequence}
      closedNote={closedNote}
      onKeepWorking={onDismiss}
      onConfirmClose={confirmClose}
      onDone={onDismiss}
    />
  )
}
