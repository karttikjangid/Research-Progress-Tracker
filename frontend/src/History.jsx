import { useCallback, useEffect, useState } from 'react'
import { get, post } from './api'
import { shortDate, mmss } from './format'
import EvidenceDoc from './components/EvidenceDoc'

const VCODE = { passed: 'P', failed_final: 'F', failed_once: 'F', open: 'O', done: '✓' }
const VTONE = { passed: 'dk-p', failed_final: 'dk-f', failed_once: 'dk-f', open: '', done: 'dk-p' }
const VTEXT = { passed: 'PASS', failed_final: 'FAIL', failed_once: 'FAIL', open: 'OPEN', done: 'DONE' }

// PHASE 2 — the case-file archive, wired to /api/history. Day rows drill down to
// their exhibits (tasks) and the recording audit. The glossary is live
// (search + bulk paste). The weekly synthesis is read best-effort from the
// export markdown — there is no dedicated synthesis endpoint (see DEVIATIONS).
export default function History() {
  const [days, setDays] = useState(null)
  const [openDay, setOpenDay] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { get('/api/history').then(setDays).catch((e) => setError(e.message)) }, [])

  if (error) return <p className="s-err" style={{ marginTop: '30px' }}>{error}</p>
  if (!days) return <p className="dk-req" style={{ marginTop: '30px' }}>Loading the archive…</p>

  const first = days.at(-1)?.date
  const last = days[0]?.date
  const range = first && last ? `${shortDate(first)} – ${shortDate(last)}` : ''

  return (
    <>
      <EvidenceDoc tabLeft="CASE-FILE ARCHIVE" tabRight={range} style={{ marginTop: '30px' }}>
        <div style={{ padding: '4px 24px 18px' }}>
          <div className="s-hrow"><span>DATE</span><span>FILE</span><span>EXHIBITS</span><span>SESSION</span><span>STREAK</span><span></span></div>
          {days.length === 0 && <p className="dk-req">Nothing on file yet.</p>}
          {days.map((d) => {
            const open = openDay === d.date
            const gated = d.tasks.filter((t) => t.type === 'gated')
            const codes = gated.map((t, i) => `${String.fromCharCode(65 + i)}·${VCODE[t.status] || '?'}`).join(' ') || '—'
            const recSec = d.recordings.reduce((n, r) => n + (r.duration_sec || 0), 0)
            const streakM = (d.summary_line || '').match(/streak[^0-9]*(\d+)/i)
            return (
              <div key={d.date}>
                <button className="s-drow" onClick={() => setOpenDay(open ? null : d.date)} type="button">
                  <span className="fw7">{shortDate(d.date)}</span>
                  <span className="s-muted">—</span>
                  <span style={{ letterSpacing: '.06em' }}>{codes}</span>
                  <span>{recSec ? `${mmss(recSec)}` : '—'}</span>
                  <span>{streakM ? streakM[1] : '—'}</span>
                  <span>{open ? '▾' : '▸'}</span>
                </button>
                {open && (
                  <>
                    {d.summary_line && <p className="dk-req" style={{ margin: '2px 0 12px', fontStyle: 'italic' }}>{d.summary_line}</p>}
                    <div className="s-det">
                      {gated.map((t, i) => (
                        <div className="s-mini" key={t.id}>
                          <div className="fx jb ac"><span className="s-lab">EXHIBIT {String.fromCharCode(65 + i)}</span><span className={`s-vs ${VTONE[t.status] || ''}`}>{VTEXT[t.status] || t.status}</span></div>
                          <div className="fw7 mt8" style={{ fontSize: '14.5px', lineHeight: 1.35 }}>{t.title}</div>
                          <div className="dk-req">Attempts {t.attempts} of 2</div>
                          <div className="dk-dash"></div>
                          <div className="fs12 mt8" style={{ fontStyle: 'italic', lineHeight: 1.5 }}>{t.reason || 'No verdict on file.'}</div>
                        </div>
                      ))}
                      {d.recordings.map((r) => (
                        <div className="s-mini" key={`r${r.id}`}>
                          <div className="fx jb ac"><span className="s-lab">RECORDING</span><span className={`s-vs ${r.audit_viewed ? 'dk-p' : ''}`}>{r.audit_viewed ? 'AUDITED' : 'UNREAD'}</span></div>
                          <div className="fw7 mt8" style={{ fontSize: '14.5px' }}>Spoken shadowing · {mmss(r.duration_sec)}</div>
                          <div className="dk-dash"></div>
                          <div className="fs12" style={{ lineHeight: 1.5, color: 'rgba(36,31,21,.8)', maxHeight: '120px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>{r.audit}</div>
                        </div>
                      ))}
                      {gated.length === 0 && d.recordings.length === 0 && (
                        <div className="fs12 s-muted">No exhibits or recordings on this file.</div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </EvidenceDoc>

      <div className="s-panels">
        <Synthesis />
        <Glossary />
      </div>
    </>
  )
}

// Best-effort: pull the "## Weekly synthesis" section out of the export markdown.
// There is no synthesis read endpoint; POST /api/review/weekly generates it.
function Synthesis() {
  const [text, setText] = useState(undefined)
  useEffect(() => {
    fetch('/api/export').then((r) => r.text()).then((md) => {
      const i = md.indexOf('## Weekly synthesis')
      setText(i >= 0 ? md.slice(i + '## Weekly synthesis'.length).trim() : null)
    }).catch(() => setText(null))
  }, [])
  return (
    <div className="s-panel">
      <div className="s-lab">WEEKLY SYNTHESIS</div>
      {text === undefined && <p className="fs13" style={{ marginTop: '12px' }}>Loading…</p>}
      {text === null && (
        <p className="fs13" style={{ lineHeight: 1.65, margin: '12px 0 0' }}>
          No synthesis on file yet. Run the weekly review to have the examiner assemble one from the week’s record.
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
