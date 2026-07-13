import { useCallback, useEffect, useState } from 'react'
import { get, post } from './api'
import { shortDate, mmss } from './format'

const PILL = { passed: 'pass', failed_final: 'fail', failed_once: 'fail', open: 'open', done: 'pass' }
const PTEXT = { passed: 'PASS', failed_final: 'FAIL', failed_once: 'FAIL', open: 'OPEN', done: 'DONE' }
const TONE = { passed: 'dk-p', failed_final: 'dk-f', failed_once: 'dk-f', open: '', done: 'dk-p' }

const hm = (min) => {
  const m = Math.round(min || 0)
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`
}
const dayNum = (iso) => (iso ? iso.slice(8, 10) : '')
const outcome = (d) =>
  !d.summary_line ? { cls: 'progress', label: 'IN PROGRESS' }
    : d.streak_day ? { cls: 'clean', label: 'CLEAN DAY' } : { cls: 'broken', label: 'BROKEN' }

// PHASE 2 — History as plain day cards. Each day says in words how it went
// (outcome chip, named task verdicts, focus time, streak), with a trends strip
// on top (focus per day + spoken fluency) and an on-demand weekly synthesis.
export default function History() {
  const [days, setDays] = useState(null)
  const [openDay, setOpenDay] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { get('/api/history').then(setDays).catch((e) => setError(e.message)) }, [])

  if (error) return <p className="s-err" style={{ marginTop: '30px' }}>{error}</p>
  if (!days) return <p className="dk-req" style={{ marginTop: '30px' }}>Loading the archive…</p>

  const range = days.length ? `${shortDate(days.at(-1).date)} – ${shortDate(days[0].date)}` : ''
  const chrono = [...days].reverse()
  const focusData = chrono.map((d) => ({ label: dayNum(d.date), v: d.focus_minutes || 0 }))
  const focusMax = Math.max(1, ...focusData.map((d) => d.v))
  const vocal = chrono
    .map((d) => {
      const r = [...d.recordings].reverse().find((x) => x.wpm != null)
      return r ? { label: dayNum(d.date), v: r.fillers_per_min, wpm: r.wpm } : null
    })
    .filter(Boolean)
  const vocalMax = Math.max(1, ...vocal.map((d) => d.v))
  const lastWpm = vocal.length ? vocal[vocal.length - 1].wpm : null

  return (
    <>
      <div className="s-trends">
        <div className="s-chart-box">
          <div className="s-lab">FOCUS PER DAY</div>
          <BarChart data={focusData} max={focusMax} />
          <div className="s-chart-cap">Minutes of logged focus sessions.</div>
        </div>
        <div className="s-chart-box">
          <div className="s-lab">SPOKEN FLUENCY · FILLERS / MIN</div>
          {vocal.length ? (
            <>
              <BarChart data={vocal} max={vocalMax} v />
              <div className="s-chart-cap">Lower is better{lastWpm ? ` · latest ${lastWpm} wpm` : ''}.</div>
            </>
          ) : (
            <div className="s-chart-empty">No drills audited yet. Record one on the RECORD tab and the trend appears here.</div>
          )}
        </div>
      </div>

      <div className="fx jb ac" style={{ marginTop: '30px' }}>
        <div className="dk-osw fs14">CASE-FILE ARCHIVE</div>
        <div className="fs13" style={{ opacity: .6 }}>{range}</div>
      </div>

      {days.length === 0 && <p className="dk-req" style={{ marginTop: '14px' }}>Nothing on file yet.</p>}

      <div className="s-days">
        {days.map((d) => {
          const oc = outcome(d)
          const gated = d.tasks.filter((t) => t.type === 'gated')
          const simple = d.tasks.filter((t) => t.type === 'simple')
          const ticksDone = simple.filter((t) => t.status === 'done').length
          const rec = d.recordings.at(-1)
          const open = openDay === d.date
          return (
            <div key={d.date} className="s-day">
              <button className="s-day-head" type="button" onClick={() => setOpenDay(open ? null : d.date)}>
                <span className="s-day-date">{shortDate(d.date)}</span>
                <span className={`s-chip ${oc.cls}`}>{oc.label}</span>
                <span className="s-pills">
                  {gated.map((t) => (
                    <span key={t.id} className={`s-pill ${PILL[t.status] || 'open'}`} title={t.title}>
                      {t.title} — {PTEXT[t.status] || t.status}
                    </span>
                  ))}
                  {simple.length > 0 && <span className="s-pill tick">{ticksDone}/{simple.length} TICKS</span>}
                  {rec && <span className={`s-pill ${rec.audit_viewed ? 'pass' : 'open'}`}>VERBAL — {rec.audit_viewed ? 'AUDITED' : 'UNREAD'}</span>}
                </span>
                <span className="s-day-metric"><div className="s-metric-lab">FOCUS</div><div className="s-metric-val">{hm(d.focus_minutes)}</div></span>
                <span className="s-day-metric"><div className="s-metric-lab">STREAK</div><div className="s-metric-val">{d.current_streak ?? '—'}</div></span>
                <span className="s-day-car">{open ? '▾' : '▸'}</span>
              </button>
              {d.summary_line && <div className="s-day-sum">{d.summary_line}</div>}
              {open && (
                <div className="s-day-detail">
                  {gated.map((t) => (
                    <div className="s-mini" key={t.id}>
                      <div className="fx jb ac"><span className="s-lab">GATED EXHIBIT</span><span className={`s-vs ${TONE[t.status] || ''}`}>{PTEXT[t.status] || t.status}</span></div>
                      <div className="fw7 mt8" style={{ fontSize: '14.5px', lineHeight: 1.35 }}>{t.title}</div>
                      <div className="dk-req">Attempts {t.attempts} of 2</div>
                      <div className="dk-dash"></div>
                      <div className="fs12" style={{ fontStyle: 'italic', lineHeight: 1.5 }}>{t.reason || 'No verdict on file.'}</div>
                    </div>
                  ))}
                  {d.recordings.map((r) => (
                    <div className="s-mini" key={`r${r.id}`}>
                      <div className="fx jb ac"><span className="s-lab">VERBAL DRILL</span><span className={`s-vs ${r.audit_viewed ? 'dk-p' : ''}`}>{r.audit_viewed ? 'AUDITED' : 'UNREAD'}</span></div>
                      <div className="fw7 mt8" style={{ fontSize: '14.5px' }}>{mmss(r.duration_sec)} single take</div>
                      {r.wpm != null && <div className="dk-req">{r.wpm} wpm · {r.fillers_per_min}/min fillers · {Math.round(r.unique_ratio * 100)}% unique words</div>}
                      <div className="dk-dash"></div>
                      <div className="fs12" style={{ lineHeight: 1.5, color: 'rgba(36,31,21,.8)', maxHeight: '150px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>{r.audit}</div>
                    </div>
                  ))}
                  {d.reflection && (
                    <div className="s-mini">
                      <div className="s-lab">END-OF-DAY CONSOLIDATION</div>
                      <div className="fs13 mt8" style={{ lineHeight: 1.5 }}>
                        <span className="fw7">Understood:</span> {d.reflection.understood || '—'}
                      </div>
                      {d.reflection.sticking_point && (
                        <>
                          <div className="dk-dash"></div>
                          <div className="fs12" style={{ lineHeight: 1.5, fontStyle: 'italic' }}>
                            <span className="fw7">Stuck on:</span> {d.reflection.sticking_point}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                  {gated.length === 0 && d.recordings.length === 0 && !d.reflection && <div className="fs12 s-muted">No exhibits, recordings, or reflection on this file.</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="s-panels">
        <Synthesis />
        <Glossary />
      </div>
    </>
  )
}

function BarChart({ data, max, v = false }) {
  return (
    <div className="s-chart">
      {data.map((d, i) => (
        <div className="s-bar-col" key={i}>
          <div className={`s-bar${v ? ' v' : ''}`} style={{ height: `${Math.max(2, Math.round((d.v / max) * 100))}%` }} title={`${d.v}`}></div>
          <span className="s-bar-lab">{d.label}</span>
        </div>
      ))}
    </div>
  )
}

// Weekly synthesis, read best-effort from the export markdown; the button
// generates it on the spot (POST /api/review/weekly → LLM re-grade + synthesis).
function Synthesis() {
  const [text, setText] = useState(undefined)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState('')
  const load = useCallback(() =>
    fetch('/api/export').then((r) => r.text()).then((md) => {
      const i = md.indexOf('## Weekly synthesis')
      setText(i >= 0 ? md.slice(i + '## Weekly synthesis'.length).trim() : null)
    }).catch(() => setText(null)), [])
  useEffect(() => { load() }, [load])

  const run = () => {
    setRunning(true); setErr('')
    post('/api/review/weekly').then(() => load()).catch((e) => setErr(e.message)).finally(() => setRunning(false))
  }
  return (
    <div className="s-panel">
      <div className="fx jb ac">
        <div className="s-lab">WEEKLY SYNTHESIS</div>
        <button className="s-run-btn" type="button" onClick={run} disabled={running}>{running ? 'ASSEMBLING…' : 'RUN WEEKLY REVIEW'}</button>
      </div>
      {err && <p className="s-err" style={{ margin: '10px 0 0' }}>{err}</p>}
      {text === undefined && <p className="fs13" style={{ marginTop: '12px' }}>Loading…</p>}
      {text === null && !err && (
        <p className="fs13" style={{ lineHeight: 1.65, margin: '12px 0 0' }}>
          No synthesis on file yet. Run the weekly review — the examiner re-grades a sample of the week’s passes and assembles a synthesis from the record.
        </p>
      )}
      {text && <p className="fs13" style={{ lineHeight: 1.65, margin: '12px 0 0', whiteSpace: 'pre-wrap' }}>{text}</p>}
    </div>
  )
}

// Glossary: live search + bulk-paste of the daily decode markdown table.
function Glossary() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [paste, setPaste] = useState('')
  const [msg, setMsg] = useState('')
  const search = useCallback((query) =>
    get(`/api/glossary?q=${encodeURIComponent(query)}`).then(setRows).catch(() => setRows([])), [])
  useEffect(() => { search('') }, [search])

  const submit = () =>
    post('/api/glossary', { paste }).then((r) => {
      setMsg(`added ${r.added.length}, rejected ${r.rejected.length}`)
      setPaste(''); search(q)
    }).catch((e) => setMsg(e.message))

  return (
    <div className="s-panel">
      <div className="s-lab">VOCABULARY &amp; NOTATION GLOSSARY</div>
      <input className="s-inp mt12" placeholder="Search terms…" value={q}
        onChange={(e) => { setQ(e.target.value); search(e.target.value) }} />
      <div className="mt8" style={{ maxHeight: '200px', overflowY: 'auto' }}>
        {rows.map((g) => (
          <div className="s-gent" key={g.id}>
            <span className="fw7">{g.symbol}</span>
            {g.type_annotation && <span className="s-muted"> : {g.type_annotation}</span>}
            {' '}— {g.meaning}
            {g.is_overload && <span className="s-vs dk-f" style={{ marginLeft: '8px', fontSize: '9px', padding: '1px 6px' }}>OVERLOADED</span>}
          </div>
        ))}
        {rows.length === 0 && <div className="s-gent s-muted">No entry matches.</div>}
      </div>
      <textarea className="s-ta mt12" rows={3} value={paste} onChange={(e) => setPaste(e.target.value)}
        placeholder="Bulk paste: | symbol | type | meaning | source |" />
      <div className="fx ac gap8" style={{ marginTop: '10px' }}>
        <button className="s-mini-btn" type="button" onClick={submit} disabled={!paste.trim()}>ADD ROWS</button>
        {msg && <span className="s-hint" style={{ margin: 0 }}>{msg}</span>}
      </div>
    </div>
  )
}
