import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get, post } from './api'
import { clock, todayISO } from './format'
import StreakChip from './components/StreakChip'
import ThemeStrip from './components/ThemeStrip'
import ExhibitCard from './components/ExhibitCard'
import TicksStrip from './components/TicksStrip'
import GatedFlow from './components/GatedFlow'

const REQ = 'Evidence required · examined on submission · verdict final'
const SESSION_KEY = 'gk_session'
// Fanned-card geometry. Left positions are computed from the measured fan width
// so the three cards spread to fill wide panels instead of clustering centre;
// focus pulls a card toward the centre. CW = card width.
const CW = 372, GAP = 72
const TOPS = [36, 2, 42], ROTS = [-3, 0, 2.4], ZS = [1, 3, 2]
const FOCUS_TOP = 8
// 0 for exhibits still awaiting a verdict, 1 for resolved — used to keep
// actionable exhibits in the fan when there are more than three on file.
const unresolvedFirst = (t) => (t.status === 'open' || t.status === 'failed_once' ? 0 : 1)

export default function Today({ closed = false, streak, theme, weekLabel, onStreakChange }) {
  const [data, setData] = useState(null)
  const [recent, setRecent] = useState([])
  const [error, setError] = useState('')
  const [gating, setGating] = useState(null)
  const [focused, setFocused] = useState(null) // task id of the pulled-forward card
  const [dealt, setDealt] = useState(false)     // fan has finished dealing in
  const [session, setSession] = useState(() => {
    try { return JSON.parse(localStorage.getItem(SESSION_KEY)) } catch { return null }
  })
  const [now, setNow] = useState(() => Date.now())
  const [struck, setStruck] = useState(() => new Set())
  const prevVerdicts = useRef({})
  const fanRef = useRef(null)
  const [fanW, setFanW] = useState(1400)

  // Measure the fan so cards spread across the panel's real width.
  useEffect(() => {
    const el = fanRef.current
    if (!el) return
    setFanW(el.clientWidth)
    const ro = new ResizeObserver((es) => { for (const e of es) setFanW(e.contentRect.width) })
    ro.observe(el)
    return () => ro.disconnect()
  }, [data])

  // Guard against out-of-order responses: a slow earlier GET /api/tasks must not
  // overwrite state set by a later one (e.g. the mount fetch resolving after the
  // post-create refetch — which made a freshly filed exhibit vanish until reload).
  // Only the most recent request's result is applied.
  const reqSeq = useRef(0)
  const refresh = useCallback(() => {
    const seq = ++reqSeq.current
    return get('/api/tasks')
      .then((d) => { if (seq === reqSeq.current) { setData(d); setError('') } })
      .catch((e) => { if (seq === reqSeq.current) setError(e.message) })
  }, [])
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { get('/api/history').then(setRecent).catch(() => setRecent([])) }, [])

  // The deal-in stagger only applies to the first render; later animations snap.
  useEffect(() => { const t = setTimeout(() => setDealt(true), 900); return () => clearTimeout(t) }, [])
  // Escape closes focus mode.
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') setFocused(null) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

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
  const endSession = (task) => {
    if (!session) return
    post(`/api/sessions/${session.id}/end`).then(() => {
      storeSession(null)
      onStreakChange?.()
      // Ending a timed session on a gated exhibit hands it straight to the
      // examiner: open the evidence flow so questions are asked and a verdict
      // recorded. Skip if the exhibit is already resolved (passed / locked).
      if (task && (task.status === 'open' || task.status === 'failed_once')) setGating(task)
    }).catch((e) => { setError(e.message); storeSession(null) })
  }
  const completeTick = (id) =>
    post(`/api/tasks/${id}/complete`).then(refresh).catch((e) => setError(e.message))

  if (!data) return <p className="dk-req" style={{ marginTop: '28px' }}>{error || 'Loading the file…'}</p>

  const gatedAll = data.tasks.filter((t) => t.type === 'gated')
  // The fan has three slots. Normally there are at most three gated exhibits
  // (the backend caps manual gated at 3/day), so filing order is preserved. When
  // recall tasks push the count past three, order unresolved exhibits first so a
  // freshly filed or spawned one is never silently hidden behind a resolved card.
  const overflow = gatedAll.length > 3
  const gated = (overflow
    ? [...gatedAll].sort((a, b) => unresolvedFirst(a) - unresolvedFirst(b))
    : gatedAll).slice(0, 3)
  const simple = data.tasks.filter((t) => t.type === 'simple')
  const elapsed = session ? Math.max(0, Math.floor((now - Date.parse(session.started_at)) / 1000)) : 0

  // Spread the cards across the measured width; fall back to a light overlap on
  // narrow panels. focusLeft is the centre a card animates to when focused.
  const blockW = CW * 3 + GAP * 2
  const spread = fanW >= blockW
  const startX = spread ? (fanW - blockW) / 2 : 0
  const leftOf = (i) => Math.round(spread ? startX + i * (CW + GAP) : [0, (fanW - CW) / 2, fanW - CW][i])
  const focusLeft = Math.round((fanW - CW) / 2)

  const statusMeta = {
    passed: { label: 'RESOLVED', verdict: 'PASS' },
    failed_final: { label: 'RESOLVED', verdict: 'FAIL' },
    failed_once: { label: 'OPEN — RETRY', verdict: 'FAIL' },
    open: { label: 'OPEN', verdict: null },
  }
  const reasonFor = (t) => {
    if (t.status === 'open') return 'No verdict until evidence is submitted. Closing the day files the exhibit as-is.'
    if (t.status === 'failed_once') return `${t.reason} — one retry left; file a revised artifact.`
    if (t.status === 'failed_final') return `${t.reason} — failed twice; locked until tomorrow.`
    return t.reason
  }

  // Session-area node for one exhibit (live timer, begin/end).
  const sessionSlot = (t) => {
    const unresolved = t.status === 'open' || t.status === 'failed_once'
    const mine = session && session.task_id === t.id
    if (mine) {
      return (
        <div className="fx jb ac">
          <div><div className="s-lab">SESSION RUNNING</div><div className="dk-time mt8">{clock(elapsed)}</div></div>
          <div className="fx col gap8" style={{ alignItems: 'flex-end' }}>
            <span className="dk-sess">IN SESSION</span>
            <button className="s-mini-btn dk-f" type="button" onClick={(e) => { e.stopPropagation(); endSession(t) }}>■ END</button>
          </div>
        </div>
      )
    }
    if (unresolved) {
      return (
        <div className="fx jb ac">
          <div><div className="s-lab">SESSION</div><div className="dk-time mt8 s-muted">—:—:—</div></div>
          <button className="s-mini-btn" type="button" disabled={!!session}
            title={session ? 'Another session is running' : 'Begin a timed session'}
            onClick={(e) => { e.stopPropagation(); beginSession(t.id) }}>▶ START</button>
        </div>
      )
    }
    return (<><div className="s-lab">ATTEMPTS</div><div className="dk-time mt8">{t.attempts} <span className="fs13 s-muted">of 2</span></div></>)
  }

  const footerFor = (t) => {
    const unresolved = t.status === 'open' || t.status === 'failed_once'
    return (
      <>
        {unresolved && (
          <button className="s-mini-btn" type="button" onClick={(e) => { e.stopPropagation(); setGating(t) }}>
            {t.status === 'failed_once' ? 'FILE REVISED EVIDENCE' : 'FILE EVIDENCE'}
          </button>
        )}
        <button className="dk-close" type="button" onClick={(e) => { e.stopPropagation(); setFocused(null) }}>✕ CLOSE</button>
      </>
    )
  }

  return (
    <>
      {error && <p className="s-err" style={{ marginTop: '24px' }}>{error}</p>}

      <AnimatePresence>
        {focused != null && (
          <motion.div className="s-focus-backdrop" onClick={() => setFocused(null)}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .2 }} />
        )}
      </AnimatePresence>

      {closed && (
        <div className="s-panel fx ac gap16" style={{ marginTop: '24px', transform: 'rotate(-.4deg)' }}>
          <span className="s-vs dk-f">FILE CLOSED</span>
          <span className="fs13">Today is recorded. The ledger reopens at 00:00.</span>
        </div>
      )}

      <div className="fx jb mt24" style={{ alignItems: 'flex-start' }}>
        <StreakChip
          day={closed ? 0 : (streak?.current_streak ?? '—')}
          note={closed ? 'BROKEN — RESETS AT 00:00' : streak ? `STREAK INTACT · LONGEST ${streak.longest_streak}` : 'STREAK'} />
        <SevenDayMarks days={buildLast7(recent)} />
        <ThemeStrip theme={theme || '—'} label={weekLabel} />
      </div>

      {gated.length === 0 ? (
        <div className="s-panel" style={{ marginTop: '30px' }}>
          <div className="dk-osw fs12" style={{ letterSpacing: '.22em' }}>NO EXHIBITS FILED</div>
          <p className="fs13 m0" style={{ marginTop: '10px', lineHeight: 1.6 }}>
            No gated tasks today. File an exhibit below to put demanding work behind the examiner.
          </p>
        </div>
      ) : (
        <div className="dk-fan" ref={fanRef} style={{ zIndex: focused != null ? 50 : 'auto' }}>
          {gated.map((t, i) => {
            const meta = statusMeta[t.status] || { label: t.status.toUpperCase(), verdict: null }
            const base = { left: leftOf(i), top: TOPS[i], rot: ROTS[i], z: ZS[i] }
            const rest = { x: 0, y: 0, rotate: base.rot, scale: 1, opacity: 1, filter: 'blur(0px)', zIndex: base.z }
            const foc = { x: focusLeft - base.left, y: FOCUS_TOP - base.top, rotate: 0, scale: 1.12, opacity: 1, filter: 'blur(0px)', zIndex: 60 }
            const dim = { x: 0, y: 0, rotate: base.rot, scale: 0.92, opacity: 0.28, filter: 'blur(3px)', zIndex: base.z }
            const target = focused === t.id ? foc : focused != null ? dim : rest
            return (
              <ExhibitCard
                key={t.id}
                letter={String.fromCharCode(65 + i)}
                statusLabel={meta.label}
                title={t.title}
                req={REQ}
                verdict={meta.verdict}
                struck={struck.has(t.id)}
                reason={reasonFor(t)}
                focused={focused === t.id}
                footer={footerFor(t)}
                onClick={() => setFocused((f) => (f === t.id ? f : t.id))}
                motionProps={{
                  style: { left: base.left, top: base.top },
                  initial: { opacity: 0, y: -50, rotate: 0, scale: 0.9 },
                  animate: target,
                  transition: { type: 'spring', stiffness: 280, damping: 28, delay: dealt ? 0 : 0.05 + i * 0.1 },
                  whileHover: focused == null ? { y: -6, scale: 1.02, transition: { type: 'spring', stiffness: 400, damping: 20 } } : undefined,
                }}
              >
                {sessionSlot(t)}
              </ExhibitCard>
            )
          })}
        </div>
      )}

      {overflow && (
        <div className="dk-req tc" style={{ marginTop: '12px' }}>
          Showing three of {gatedAll.length} filed exhibits — unresolved ones first.
        </div>
      )}

      <TicksStrip ticks={buildTicks(simple, data.verbal, completeTick)} />

      <div className="dk-foot">SINGLE EXAMINER · EVIDENCE ONLY · VERDICTS BINDING — NO APPEALS, NO SCORES</div>

      <Ancillary onChange={() => { refresh(); onStreakChange?.() }} />

      <AnimatePresence>
        {gating && <GatedFlow key="gated" task={gating} onDone={() => { setGating(null); refresh(); onStreakChange?.() }} />}
      </AnimatePresence>
    </>
  )
}

// ---- last-7-days marks ----------------------------------------------------
const DOW1 = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

function buildLast7(days) {
  const map = Object.fromEntries((days || []).map((d) => [d.date, d]))
  const base = new Date()
  const out = []
  for (let k = 6; k >= 0; k--) {
    const dt = new Date(base); dt.setDate(base.getDate() - k)
    const iso = dt.toISOString().slice(0, 10)
    const d = map[iso]
    let state = 'none'
    if (d) state = d.streak_day ? 'clean' : d.summary_line ? 'broken' : 'open'
    out.push({ iso, dow: DOW1[dt.getDay()], state, today: iso === todayISO() })
  }
  return out
}

function SevenDayMarks({ days }) {
  return (
    <div className="tc">
      <div className="s-marks-lab">LAST 7 DAYS</div>
      <div className="s-marks">
        {days.map((d) => (
          <div key={d.iso} className={`s-mark ${d.state}${d.today ? ' today' : ''}`} title={`${d.iso} — ${d.state}`}>
            <span className="s-mark-d">{d.dow}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// Free ticks = simple tasks (one-way complete) + the synthetic verbal-drill row.
function buildTicks(simple, verbal, complete) {
  const ticks = simple.map((t) => ({
    label: t.title, done: t.status === 'done',
    onToggle: t.status === 'done' ? undefined : () => complete(t.id),
  }))
  ticks.push({
    label: verbal.done ? 'Verbal drill — audited' : verbal.recorded ? 'Verbal drill — audit unread (RECORD tab)' : 'Verbal drill — not recorded (RECORD tab)',
    done: verbal.done, onToggle: undefined,
  })
  return ticks
}

// ---- ancillary record: wired features the export did not depict -----------
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

function FileItem({ onChange }) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState('gated')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const add = (e) => {
    e.preventDefault()
    if (!title.trim() || busy) return
    setBusy(true); setErr('')
    post('/api/tasks', { title, type })
      .then(() => { setTitle(''); onChange?.() })
      .catch((er) => setErr(er.message))
      .finally(() => setBusy(false))
  }
  return (
    <form className="s-card" onSubmit={add}>
      <div className="s-lab">FILE A NEW ITEM</div>
      {err && <p className="s-err" style={{ margin: '8px 0' }}>{err}</p>}
      <div className="fx gap8" style={{ marginTop: '10px', alignItems: 'center' }}>
        <input className="s-inp" style={{ flex: 1 }} value={title} placeholder="What must be done…" disabled={busy} onChange={(e) => setTitle(e.target.value)} />
        <select className="s-sel" value={type} disabled={busy} onChange={(e) => setType(e.target.value)}>
          <option value="gated">gated exhibit</option>
          <option value="simple">free tick</option>
        </select>
        <button className="s-mini-btn" type="submit" disabled={busy || !title.trim()}>{busy ? 'FILING…' : 'FILE'}</button>
      </div>
      <div className="s-hint">Gated exhibits require evidence (up to 3/day); free ticks are self-certified.</div>
    </form>
  )
}

function DueReviews({ onChange }) {
  const [due, setDue] = useState([])
  const [open, setOpen] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => get('/api/reviews/due').then(setDue).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  const reveal = (id) => post(`/api/reviews/${id}/reveal`).then((r) => setOpen({ id, ...r })).catch((e) => setErr(e.message))
  const grade = (id, g) => {
    if (busy) return
    setBusy(true); setErr('')
    post(`/api/reviews/${id}/grade`, { grade: g })
      .then(() => { setOpen(null); load(); onChange?.() })
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false))
  }

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
                    <button key={g} className="s-mini-btn" type="button" disabled={busy} onClick={() => grade(r.id, g)}>{g.toUpperCase()}</button>
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

// End-of-day consolidation: one retrieval prompt (what you can explain now that
// you couldn't this morning) + the day's hardest sticking point, which the
// backend schedules as tomorrow's spaced-repetition review. Immutable once
// written. Yesterday's line is surfaced as a light continuity/recall cue.
function TasteLog() {
  const [existing, setExisting] = useState(undefined)
  const [yday, setYday] = useState(null)
  const [understood, setUnderstood] = useState('')
  const [stuck, setStuck] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { get('/api/tastelog').then(setExisting).catch(() => setExisting(null)) }, [])
  useEffect(() => {
    const d = new Date(); d.setDate(d.getDate() - 1)
    get(`/api/tastelog?date=${d.toISOString().slice(0, 10)}`).then(setYday).catch(() => setYday(null))
  }, [])

  const submit = (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setErr('')
    post('/api/tastelog', { understood, sticking_point: stuck })
      .then(setExisting).catch((er) => setErr(er.message)).finally(() => setBusy(false))
  }
  if (existing === undefined) return <div className="s-card"><div className="s-lab">END OF DAY · CONSOLIDATE</div></div>

  const ydayLine = yday && (yday.understood || yday.one_liner)
  return (
    <div className="s-card">
      <div className="s-lab">END OF DAY · CONSOLIDATE</div>
      {ydayLine && (
        <p className="s-hint" style={{ marginTop: '10px', lineHeight: 1.5 }}>
          Yesterday you understood: <span style={{ fontStyle: 'italic' }}>{ydayLine}</span>
        </p>
      )}
      {existing ? (
        <div className="fs13" style={{ marginTop: '10px', lineHeight: 1.6 }}>
          <p className="m0"><span className="fw7">Understood today:</span> {existing.understood || existing.one_liner || '—'}</p>
          {existing.sticking_point && (
            <p style={{ margin: '8px 0 0' }}>
              <span className="fw7">Stuck on:</span> {existing.sticking_point}
              <span className="s-hint"> — returns as a review tomorrow</span>
            </p>
          )}
          <span className="s-hint" style={{ display: 'block', marginTop: '6px' }}>written — immutable</span>
        </div>
      ) : (
        <form onSubmit={submit} style={{ marginTop: '10px' }}>
          {err && <p className="s-err" style={{ margin: '0 0 8px' }}>{err}</p>}
          <label className="fs12">What do you understand now that you couldn't this morning?</label>
          <textarea className="s-ta mt8" rows={3} value={understood} onChange={(e) => setUnderstood(e.target.value)}
            placeholder="The day's real consolidation, in your own words (10–500 chars). An honest 'nothing clicked' is valid data." />
          <label className="fs12" style={{ display: 'block', marginTop: '12px' }}>
            Today's hardest sticking point <span className="s-hint">— becomes tomorrow's review (optional)</span>
          </label>
          <textarea className="s-ta mt8" rows={3} value={stuck} onChange={(e) => setStuck(e.target.value)}
            placeholder="The one thing that blocked you. Leave empty if nothing stuck." />
          <div style={{ marginTop: '12px' }}><button className="s-mini-btn" type="submit" disabled={busy}>{busy ? 'WRITING…' : 'WRITE (FINAL)'}</button></div>
        </form>
      )}
    </div>
  )
}
