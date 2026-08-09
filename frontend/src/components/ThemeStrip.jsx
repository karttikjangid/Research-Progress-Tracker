import { useEffect, useRef, useState } from 'react'
import { get, put } from '../api'

// This week's theme, as a slightly counter-tilted cream strip. Now EDITABLE and
// self-contained: it reads GET /api/theme (the owner's override, or the plan's
// week.yaml default) and the label is computed from TODAY's ISO week server-side,
// so it never shows a stale week number. Click the pencil to set your own theme;
// clearing it reverts to the plan.
export default function ThemeStrip() {
  const [d, setD] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const taRef = useRef(null)

  const load = () => get('/api/theme').then(setD).catch(() => {})
  useEffect(() => { load() }, [])
  useEffect(() => { if (editing && taRef.current) taRef.current.focus() }, [editing])

  const label = d ? `WEEK ${d.week} THEME` : 'WEEK THEME'
  const begin = () => { setDraft(d?.theme || ''); setEditing(true) }
  const save = () => {
    setBusy(true)
    put('/api/theme', { theme: draft }).then(setD)
      .catch(() => {}).finally(() => { setBusy(false); setEditing(false) })
  }
  const revert = () => {
    setBusy(true)
    put('/api/theme', { theme: '' }).then(setD)
      .catch(() => {}).finally(() => { setBusy(false); setEditing(false) })
  }
  const onKey = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save()
    if (e.key === 'Escape') setEditing(false)
  }

  return (
    <div className="dk-strip">
      <div className="th-lab-row">
        <span className="fs11" style={{ letterSpacing: '.18em', opacity: .65 }}>{label}</span>
        {!editing && (
          <button className="th-edit" type="button" onClick={begin} title="Edit this week’s theme" aria-label="Edit theme">✎</button>
        )}
      </div>
      {editing ? (
        <div className="th-edit-box">
          <textarea ref={taRef} className="th-ta" rows={3} value={draft}
            onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey}
            placeholder="What is this week actually about?" />
          <div className="th-edit-actions">
            <button className="s-mini-btn dk-p" type="button" onClick={save} disabled={busy}>SAVE</button>
            <button className="s-mini-btn" type="button" onClick={() => setEditing(false)} disabled={busy}>CANCEL</button>
            {d?.custom && <button className="s-mini-btn" type="button" onClick={revert} disabled={busy} title="Use the plan’s theme">REVERT TO PLAN</button>}
          </div>
        </div>
      ) : (
        <button className="th-view" type="button" onClick={begin} title="Click to edit">
          <span className="fs16 fw7">{d ? (d.theme || 'No theme set — click to add one.') : '—'}</span>
        </button>
      )}
    </div>
  )
}
