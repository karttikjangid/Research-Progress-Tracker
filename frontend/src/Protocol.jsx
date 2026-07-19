import { useEffect, useState } from 'react'
import { get } from './api'

// PROTOCOL — the daily operating system as standing orders + a live docket.
// Unlike the roadmap (a dated mission that progresses), this is the recurring
// loop the work runs on. The daily_schedule is the authoritative clock; a live
// "NOW" marker tracks wall-clock time against it. Read-only: rendered from
// Daily_protocol.json, no writes, no completion tracking (that's the point —
// "track inputs, not outcomes").

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

export default function Protocol() {
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

      {orders.length > 0 && (
        <section className="pr-section">
          <div className="pr-h">Standing orders</div>
          <div className="pr-orders">
            {orders.map((o, i) => (
              <div className="pr-order" key={o.id || i}>
                <div className="pr-order-num">{String(i + 1).padStart(2, '0')}</div>
                <div>
                  <div className="pr-order-title">{o.title}</div>
                  {o.explanation && <p className="pr-order-exp">{o.explanation}</p>}
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
