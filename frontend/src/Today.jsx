import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from './api'
import { clock } from './format'
import StreakChip from './components/StreakChip'
import ThemeStrip from './components/ThemeStrip'
import ExhibitCard from './components/ExhibitCard'
import TicksStrip from './components/TicksStrip'
import GatedFlow from './components/GatedFlow'

const POS = ['dk-c1', 'dk-c2', 'dk-c3']
const REQ = 'Evidence required · examined on submission · verdict final'
const SESSION_KEY = 'gk_session'

// PHASE 2 — Today, wired to /api/tasks. Gated tasks fill the fanned exhibit
// cards (verdict stamps + the one-retry-then-locked flow); simple tasks are the
// free ticks. A single work session (the backend permits one open at a time) is
// associated to an exhibit client-side so its live timer can show on that card —
// the backend still measures duration and earns timer_honored server-side.
export default function Today({ closed = false, streak, theme, onStreakChange }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [gating, setGating] = useState(null)
  const [session, setSession] = useState(() => {
    try { return JSON.parse(localStorage.getItem(SESSION_KEY)) } catch { return null }
  })
  const [now, setNow] = useState(() => Date.now())
  const [struck, setStruck] = useState(() => new Set())
  const prevVerdicts = useRef({})

  const refresh = useCallback(() =>
    get('/api/tasks').then((d) => { setData(d); setError('') }).catch((e) => setError(e.message)), [])
  useEffect(() => { refresh() }, [refresh])

  // Tick the active session's cosmetic clock (duration is authoritative server-side).
  useEffect(() => {
    if (!session) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [session])

  // Strike a stamp in only when a verdict first resolves during this session.
  useEffect(() => {
    if (!data) return
    const gated = data.tasks.filter((t) => t.type === 'gated')
    const fresh = new Set()
    for (const t of gated) {
      if (t.verdict && prevVerdicts.current[t.id] !== t.verdict) fresh.add(t.id)
      prevVerdicts.current[t.id] = t.verdict
    }
    if (fresh.size) {
      setStruck((s) => new Set([...s, ...fresh]))
      const to = setTimeout(() => setStruck((s) => {
        const n = new Set(s); fresh.forEach((id) => n.delete(id)); return n
      }), 700)
      return () => clearTimeout(to)
    }
  }, [data])

  const storeSession = (v) => {
    if (v) localStorage.setItem(SESSION_KEY, JSON.stringify(v))
    else localStorage.removeItem(SESSION_KEY)
    setSession(v)
  }
  const beginSession = (taskId) =>
    post('/api/sessions/start', { kind: 'struggle_timer', planned_minutes: 20 })
      .then((sess) => storeSession({ ...sess, task_id: taskId }))
      .catch((e) => setError(e.message))
  const endSession = () => {
    if (!session) return
    post(`/api/sessions/${session.id}/end`).then(() => { storeSession(null); onStreakChange?.() })
      .catch((e) => { setError(e.message); storeSession(null) })
  }

  const completeTick = (id) =>
    post(`/api/tasks/${id}/complete`).then(refresh).catch((e) => setError(e.message))

  if (!data) return <p className="dk-req" style={{ marginTop: '28px' }}>{error || 'Loading the file…'}</p>

  const gated = data.tasks.filter((t) => t.type === 'gated').slice(0, 3)
  const simple = data.tasks.filter((t) => t.type === 'simple')
  const elapsed = session ? Math.max(0, Math.floor((now - Date.parse(session.started_at)) / 1000)) : 0

  const statusMeta = {
    passed: { label: 'RESOLVED', verdict: 'PASS' },
    failed_final: { label: 'RESOLVED', verdict: 'FAIL' },
    failed_once: { label: 'OPEN — RETRY', verdict: 'FAIL' },
    open: { label: 'OPEN', verdict: null },
  }

  const reasonFor = (t) => {
    if (t.status === 'open') return 'No verdict until evidence is submitted. Closing the day files the exhibit as-is.'
    if (t.status === 'failed_once') return `${t.reason} — one retry left; open to file a revised artifact.`
    if (t.status === 'failed_final') return `${t.reason} — failed twice; locked until tomorrow.`
    return t.reason
  }

  // The session-area node for one exhibit.
  const sessionSlot = (t) => {
    const unresolved = t.status === 'open' || t.status === 'failed_once'
    const mine = session && session.task_id === t.id
    if (mine) {
      return (
        <div className="fx jb ac">
          <div>
            <div className="s-lab">SESSION RUNNING</div>
            <div className="dk-time mt8">{clock(elapsed)}</div>
          </div>
          <div className="fx col gap8" style={{ alignItems: 'flex-end' }}>
            <span className="dk-sess">IN SESSION</span>
            <button className="s-mini-btn dk-f" type="button"
              onClick={(e) => { e.stopPropagation(); endSession() }}>■ END</button>
          </div>
        </div>
      )
    }
    if (unresolved) {
      return (
        <div className="fx jb ac">
          <div>
            <div className="s-lab">SESSION</div>
            <div className="dk-time mt8 s-muted">—:—:—</div>
          </div>
          <button className="s-mini-btn" type="button" disabled={!!session}
            title={session ? 'Another session is running' : 'Begin a timed session'}
            onClick={(e) => { e.stopPropagation(); beginSession(t.id) }}>▶ BEGIN</button>
        </div>
      )
    }
    // resolved — no per-task timer exists in the backend; show real attempt count.
    return (
      <>
        <div className="s-lab">ATTEMPTS</div>
        <div className="dk-time mt8">{t.attempts} <span className="fs13 s-muted">of 2</span></div>
      </>
    )
  }

  return (
    <>
      {error && <p className="s-err" style={{ marginTop: '24px' }}>{error}</p>}

      {closed && (
        <div className="s-panel fx ac gap16" style={{ marginTop: '24px', transform: 'rotate(-.4deg)' }}>
          <span className="s-vs dk-f">FILE CLOSED</span>
          <span className="fs13">Today is recorded. The ledger reopens at 00:00.</span>
        </div>
      )}

      <div className="fx jb mt24" style={{ alignItems: 'flex-start' }}>
        <StreakChip
          day={closed ? 0 : (streak?.current_streak ?? '—')}
          note={closed ? 'BROKEN — RESETS AT 00:00'
            : streak ? `STREAK INTACT · LONGEST ${streak.longest_streak}` : 'STREAK'} />
        <ThemeStrip theme={theme || '—'} />
      </div>

      {gated.length === 0 ? (
        <div className="s-panel" style={{ marginTop: '30px' }}>
          <div className="dk-osw fs12" style={{ letterSpacing: '.22em' }}>NO EXHIBITS FILED</div>
          <p className="fs13 m0" style={{ marginTop: '10px', lineHeight: 1.6 }}>
            No gated tasks today. File an exhibit below to put demanding work behind the examiner.
          </p>
        </div>
      ) : (
        <div className="dk-fan">
          {gated.map((t, i) => {
            const meta = statusMeta[t.status] || { label: t.status.toUpperCase(), verdict: null }
            const unresolved = t.status === 'open' || t.status === 'failed_once'
            return (
              <ExhibitCard
                key={t.id}
                letter={String.fromCharCode(65 + i)}
                posClass={POS[i]}
                statusLabel={meta.label}
                title={t.title}
                req={REQ}
                verdict={meta.verdict}
                struck={struck.has(t.id)}
                reason={reasonFor(t)}
                onClick={unresolved ? () => setGating(t) : undefined}
              >
                {sessionSlot(t)}
              </ExhibitCard>
            )
          })}
        </div>
      )}

      <TicksStrip ticks={buildTicks(simple, data.verbal, completeTick)} />

      <div className="dk-foot">SINGLE EXAMINER · EVIDENCE ONLY · VERDICTS BINDING — NO APPEALS, NO SCORES</div>

      <Ancillary onChange={() => { refresh(); onStreakChange?.() }} />

      {gating && (
        <GatedFlow task={gating}
          onDone={() => { setGating(null); refresh(); onStreakChange?.() }} />
      )}
    </>
  )
}

// Free ticks = self-certified simple tasks (backend: open → done, one-way). The
// synthetic verbal-drill row (derived from today's recording) is appended as a
// read-only tick pointing at the Record tab.
function buildTicks(simple, verbal, complete) {
  const ticks = simple.map((t) => ({
    label: t.title,
    done: t.status === 'done',
    onToggle: t.status === 'done' ? undefined : () => complete(t.id),
  }))
  ticks.push({
    label: verbal.done ? 'Verbal drill — audited' : verbal.recorded ? 'Verbal drill — audit unread (RECORD tab)' : 'Verbal drill — not recorded (RECORD tab)',
    done: verbal.done,
    onToggle: undefined,
  })
  return ticks
}

// ---- ancillary record: wired features the export did not depict -----------
const ARMS = ['none', 'training', 'eval']

function Ancillary({ onChange }) {
  return (
    <div className="s-anc">
      <div className="s-anc-h">ANCILLARY RECORD</div>
      <div className="s-panels" style={{ marginTop: '16px' }}>
        <div className="fx col gap16">
          <FileItem onChange={onChange} />
          <DueReviews onChange={onChange} />
        </div>
        <TasteLog />
      </div>
    </div>
  )
}

// Create a task — the fan and the ticks are empty until something is filed, and
// the export has no creation affordance, so this lives in the ancillary strip.
function FileItem({ onChange }) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState('gated')
  const [err, setErr] = useState('')
  const add = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    post('/api/tasks', { title, type }).then(() => { setTitle(''); setErr(''); onChange?.() })
      .catch((er) => setErr(er.message))
  }
  return (
    <form className="s-card" onSubmit={add}>
      <div className="s-lab">FILE A NEW ITEM</div>
      {err && <p className="s-err" style={{ margin: '8px 0' }}>{err}</p>}
      <div className="fx gap8" style={{ marginTop: '10px', alignItems: 'center' }}>
        <input className="s-inp" style={{ flex: 1 }} value={title} placeholder="What must be done…"
          onChange={(e) => setTitle(e.target.value)} />
        <select className="s-sel" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="gated">gated exhibit</option>
          <option value="simple">free tick</option>
        </select>
        <button className="s-mini-btn" type="submit">FILE</button>
      </div>
      <div className="s-hint">Gated exhibits require evidence (up to 3/day); free ticks are self-certified.</div>
    </form>
  )
}

// Spaced repetition: title-only prompt → reveal → self-grade. Order enforced
// server-side; a 'forgot' spawns a RECALL gated task.
function DueReviews({ onChange }) {
  const [due, setDue] = useState([])
  const [open, setOpen] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() =>
    get('/api/reviews/due').then(setDue).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  const reveal = (id) => post(`/api/reviews/${id}/reveal`).then((r) => setOpen({ id, ...r })).catch((e) => setErr(e.message))
  const grade = (id, g) => post(`/api/reviews/${id}/grade`, { grade: g })
    .then(() => { setOpen(null); load(); onChange?.() }).catch((e) => setErr(e.message))

  if (!due.length) return null
  return (
    <div className="s-card">
      <div className="s-lab">REVIEWS DUE ({due.length})</div>
      {err && <p className="s-err" style={{ margin: '8px 0' }}>{err}</p>}
      <div style={{ marginTop: '10px' }}>
        {due.map((r) => (
          <div key={r.id} style={{ padding: '8px 0', borderTop: '1px dashed rgba(36,31,21,.3)' }}>
            <div className="fx jb ac">
              <span className="fs13">{r.overdue && <span className="dk-f fw7">OVERDUE · </span>}Recall: <span className="fw7">{r.title}</span></span>
              {open?.id !== r.id && <button className="s-mini-btn" type="button" onClick={() => reveal(r.id)}>REVEAL</button>}
            </div>
            {open?.id === r.id && (
              <div style={{ marginTop: '8px' }}>
                <div className="fs12" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{open.artifact}</div>
                <p className="fs12" style={{ margin: '8px 0 0', fontStyle: 'italic' }}>Q: {open.question}</p>
                <div className="fx gap8" style={{ marginTop: '10px' }}>
                  {['recalled', 'partial', 'forgot'].map((g) => (
                    <button key={g} className="s-mini-btn" type="button" onClick={() => grade(r.id, g)}>{g.toUpperCase()}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// End-of-day taste judgment: two arm attributions + one required line. Immutable
// server-side once written.
function TasteLog() {
  const [existing, setExisting] = useState(undefined)
  const [drift, setDrift] = useState('none')
  const [dread, setDread] = useState('none')
  const [line, setLine] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { get('/api/tastelog').then(setExisting).catch(() => setExisting(null)) }, [])

  const submit = (e) => {
    e.preventDefault()
    post('/api/tastelog', { drift_arm: drift, dread_arm: dread, one_liner: line })
      .then(setExisting).catch((er) => setErr(er.message))
  }
  if (existing === undefined) return <div className="s-card"><div className="s-lab">TASTE LOG</div></div>
  return (
    <div className="s-card">
      <div className="s-lab">TASTE LOG · END OF DAY</div>
      {existing ? (
        <p className="fs13" style={{ marginTop: '10px', lineHeight: 1.6 }}>
          drift→<span className="fw7">{existing.drift_arm}</span>, dread→<span className="fw7">{existing.dread_arm}</span>: {existing.one_liner}
          <span className="s-hint" style={{ display: 'block' }}>written — immutable</span>
        </p>
      ) : (
        <form onSubmit={submit} style={{ marginTop: '10px' }}>
          {err && <p className="s-err" style={{ margin: '0 0 8px' }}>{err}</p>}
          <div className="fx gap8" style={{ alignItems: 'center' }}>
            <label className="fs12">drift
              <select className="s-sel" style={{ marginLeft: '6px' }} value={drift} onChange={(e) => setDrift(e.target.value)}>
                {ARMS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
            <label className="fs12">dread
              <select className="s-sel" style={{ marginLeft: '6px' }} value={dread} onChange={(e) => setDread(e.target.value)}>
                {ARMS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
          </div>
          <input className="s-inp mt12" value={line} onChange={(e) => setLine(e.target.value)}
            placeholder="One line (20–200 chars): what today's evidence actually was" />
          <div style={{ marginTop: '12px' }}><button className="s-mini-btn" type="submit">WRITE (FINAL)</button></div>
        </form>
      )}
    </div>
  )
}
