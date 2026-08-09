import { useCallback, useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { get, post } from './api'

// HABITS (formerly PROTOCOL) — the daily operating system, now tickable.
//
// The protocol's own motto is "track inputs, not outcomes": a non-negotiable IS
// an input, so ticking one is the motto's purest expression rather than a
// departure from it. The five non_negotiables are promoted from a read-only
// "standing orders" list into the day's live ledger at the top of the page; the
// schedule/method/weekly sections stay below as the reference they always were.
//
// Definitions live in Daily_protocol.json (single source of truth for what the
// rules ARE); only the ticks live in the DB (GET /api/habits, POST toggle).

const nowMinutes = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes() }
const toMinutes = (hhmm) => {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm || '')
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}
// The active block is the last one whose start time has passed. -1 before the
// day's first block (e.g. pre-dawn), so nothing is falsely highlighted.
const activeIndex = (schedule, cur) => {
  let idx = -1
  schedule.forEach((b, i) => { const t = toMinutes(b.time); if (t != null && t <= cur) idx = i })
  return idx
}
const clockHHMM = (cur) => `${String(Math.floor(cur / 60)).padStart(2, '0')}:${String(cur % 60).padStart(2, '0')}`
const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const dowOf = (iso) => DOW[new Date(`${iso}T00:00:00`).getDay()]

export default function Habits() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [cur, setCur] = useState(() => nowMinutes())

  useEffect(() => { get('/api/protocol').then(setData).catch((e) => setError(e.message)) }, [])
  useEffect(() => {
    const t = setInterval(() => setCur(nowMinutes()), 30000)
    return () => clearInterval(t)
  }, [])

  if (error) return <p className="s-err" style={{ marginTop: '24px' }}>{error}</p>
  if (!data) return <p className="dk-req" style={{ marginTop: '28px' }}>Opening the operating protocol…</p>

  const schedule = data.daily_schedule || []
  const orders = data.non_negotiables || []
  if (!schedule.length && !orders.length) {
    return (
      <div className="s-panel rm-empty">
        <div className="dk-osw fs12" style={{ letterSpacing: '.22em' }}>NO PROTOCOL ON FILE</div>
        <p className="fs13 m0" style={{ marginTop: '10px', lineHeight: 1.6 }}>
          The daily operating protocol is read from <code>Daily_protocol.json</code> at the project root. Add it there and this page fills in.
        </p>
      </div>
    )
  }

  const active = activeIndex(schedule, cur)

  return (
    <>
      <header className="rm-hero">
        <div className="rm-eyebrow">Operating protocol{data.version ? ` · v${data.version}` : ''}</div>
        {data.motto && <h1 className="rm-goal">{data.motto}</h1>}
        {data.success_bar && (
          <div className="rm-standard">
            <span className="rm-standard-lab">SUCCESS BAR</span>
            <p className="rm-standard-text">{data.success_bar}</p>
          </div>
        )}
      </header>

      <HabitLedger />

      {schedule.length > 0 && (
        <section className="pr-section">
          <div className="pr-h">Daily docket <span className="pr-now">● NOW {clockHHMM(cur)}</span></div>
          <div className="pr-docket">
            {schedule.map((b, i) => (
              <div className={`pr-row${i === active ? ' now' : ''}`} key={`${b.time}-${i}`}>
                <span className="pr-time">{b.time}</span>
                <div>
                  <div className="pr-block">{b.block}{i === active && <span className="pr-now-tag">NOW</span>}</div>
                  {b.note && <div className="pr-note">{b.note}</div>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {data.daily_mind_habits?.length > 0 && (
        <section className="pr-section">
          <div className="pr-h">Method</div>
          <div className="pr-cards">
            {data.daily_mind_habits.map((h, i) => (
              <div className="pr-card" key={h.id || i}>
                <div className="pr-card-head">
                  <span className="pr-card-title">{h.title}</span>
                  {h.when && <span className="pr-when">{h.when}</span>}
                </div>
                {h.explanation && <p className="pr-card-exp">{h.explanation}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {(data.weekly?.length > 0 || data.nutrition_rules?.length > 0) && (
        <div className="pr-two">
          {data.weekly?.length > 0 && (
            <div>
              <div className="pr-h">Weekly rituals</div>
              <dl className="rm-deflist">
                {data.weekly.map((w, i) => (
                  <div className="rm-def" key={w.id || i}><dt>{w.title}</dt><dd>{w.explanation}</dd></div>
                ))}
              </dl>
            </div>
          )}
          {data.nutrition_rules?.length > 0 && (
            <div>
              <div className="pr-h">Sustenance</div>
              <dl className="rm-deflist">
                {data.nutrition_rules.map((n, i) => (
                  <div className="rm-def" key={i}><dt>{n.rule}</dt><dd>{n.explanation}</dd></div>
                ))}
              </dl>
            </div>
          )}
        </div>
      )}

      {data.scorecard?.length > 0 && (
        <section className="pr-section">
          <div className="pr-h">Compliance scorecard</div>
          <div className="pr-score">
            {data.scorecard.map((s, i) => (
              <div className="pr-score-row" key={i}>
                <span className="pr-metric">{s.metric}</span>
                <span className="pr-target">{s.target}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  )
}

// The day's ledger of non-negotiables. Ticks are OPTIMISTIC — the row flips the
// instant it's pressed and reconciles against the server response, because a
// checkbox that waits on a round-trip feels dead (the single most-repeated point
// in Apple's fluid-interface guidance: respond immediately, never on release of
// a network call). A failed write rolls the row back and surfaces the error.
function HabitLedger() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [openId, setOpenId] = useState(null)
  const reduce = useReducedMotion()

  const load = useCallback(() =>
    get('/api/habits').then(setD).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  if (err) return <p className="s-err" style={{ marginTop: '24px' }}>{err}</p>
  if (!d || !d.habits.length) return null

  const { habits, done_today: done, total, target_pct: target } = d
  const pct = total ? Math.round((done / total) * 100) : 0
  const hitTarget = pct >= target

  const toggle = (h) => {
    // Optimistic: flip locally now, reconcile on response.
    setD((prev) => {
      const habits = prev.habits.map((x) => x.id === h.id
        ? { ...x, done: !x.done, streak: x.streak + (x.done ? -1 : 1) } : x)
      return { ...prev, habits, done_today: habits.filter((x) => x.done).length }
    })
    post(`/api/habits/${h.id}/toggle`, {}).then(load).catch((e) => { setErr(e.message); load() })
  }

  return (
    <section className="pr-section">
      <div className="pr-h">
        Today’s non-negotiables
        <span className="hb-count">{done}<span className="hb-count-of"> / {total}</span></span>
      </div>

      <div className="hb-ledger">
        <div className="hb-meter">
          <div className="hb-track">
            <motion.div
              className={`hb-fill${hitTarget ? ' hit' : ''}`}
              initial={false}
              animate={{ scaleX: total ? done / total : 0 }}
              transition={reduce ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.45 }}
            />
            {/* The protocol's own success bar, drawn as a line on the meter:
                the target is 70% of days, not perfection. */}
            <div className="hb-target" style={{ left: `${target}%` }} aria-hidden="true" />
          </div>
          <p className={`hb-verdict${hitTarget ? ' hit' : ''}`}>
            {hitTarget
              ? `${pct}% — above the ${target}% bar. The system is working.`
              : `${pct}% of today’s bar · ${target}% is the standard, not perfection.`}
          </p>
        </div>

        {habits.map((h) => (
          <div className={`hb-row${h.done ? ' done' : ''}`} key={h.id}>
            <button className="hb-tick" type="button" onClick={() => toggle(h)}
              aria-pressed={h.done} aria-label={`${h.done ? 'Untick' : 'Tick'} ${h.title}`}>
              <span className="hb-box">{h.done ? '×' : ' '}</span>
            </button>
            <div className="hb-body">
              <button className="hb-title-btn" type="button"
                onClick={() => setOpenId(openId === h.id ? null : h.id)}
                aria-expanded={openId === h.id}>
                <span className="hb-title">{h.title}</span>
                {h.explanation && <span className="hb-why">{openId === h.id ? '▾' : '▸'} why</span>}
              </button>
              {openId === h.id && h.explanation && (
                <p className="hb-exp">{h.explanation}</p>
              )}
              <div className="hb-week" title="Last 7 days">
                {h.week.map((w) => (
                  <span key={w.date} className={`hb-day${w.done ? ' on' : ''}`} title={w.date}>
                    {dowOf(w.date)}
                  </span>
                ))}
              </div>
            </div>
            <div className="hb-streak" title="Consecutive days">
              <span className="hb-streak-n">{h.streak}</span>
              <span className="hb-streak-lab">DAY{h.streak === 1 ? '' : 'S'}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
