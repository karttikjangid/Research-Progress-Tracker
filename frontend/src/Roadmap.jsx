import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get } from './api'
import { dueLabel, daysUntil } from './format'

// ROADMAP — the 90-day mission as a case-strategy dossier. Phases A/B/C run down
// a sealed spine; each ticket is an "exhibit" that opens into a full evidence
// sheet (scope, resources, and the two proof gates). Read-only: the plan lives
// in roadmap.json and this only renders it. Deadlines are shown as scheduling
// aids, never as completion claims — matching the plan's own standard of proof.

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const KIND = /^(MILESTONE|TASTE TRIAL|DECISION POINT)\b/

function compact(iso) {
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}`
}

// "2026-07-15 to 2026-10-15" → "15 Jul 2026 — 15 Oct 2026"
function range(win) {
  if (!win) return ''
  const [a, b] = win.split(' to ')
  return b ? `${compact(a)} — ${compact(b)}` : win
}

// Split a milestone/trial topic into its stamped kind + the readable title.
function splitTopic(topic) {
  const m = topic.match(KIND)
  if (!m) return { tag: null, title: topic }
  const parts = topic.split(' — ')
  return { tag: m[0], title: parts.slice(1).join(' — ') || topic }
}

const SPECIAL = { gsoc: 'GSoC', ai_usage: 'AI usage' }
function pretty(key) {
  if (SPECIAL[key]) return SPECIAL[key]
  const s = key.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function dueClass(iso) {
  const d = daysUntil(iso)
  if (d == null) return ''
  if (d < 0) return ' overdue'
  if (d <= 7) return ' urgent'
  return ''
}

export default function Roadmap() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [focused, setFocused] = useState(null) // the open exhibit ticket

  useEffect(() => { get('/api/roadmap').then(setData).catch((e) => setError(e.message)) }, [])
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') setFocused(null) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  if (error) return <p className="s-err" style={{ marginTop: '24px' }}>{error}</p>
  if (!data) return <p className="dk-req" style={{ marginTop: '28px' }}>Retrieving the case strategy…</p>

  const { meta, phases = [] } = data
  if (!meta) {
    return (
      <div className="s-panel rm-empty">
        <div className="dk-osw fs12" style={{ letterSpacing: '.22em' }}>NO ROADMAP ON FILE</div>
        <p className="fs13 m0" style={{ marginTop: '10px', lineHeight: 1.6 }}>
          The case strategy is read from <code>roadmap.json</code> at the project root. Add it there and this page fills in.
        </p>
      </div>
    )
  }

  const sub = splitTopic(focused?.topic || '')

  return (
    <>
      <header className="rm-hero">
        <div className="rm-eyebrow">Case strategy · 90-day brief{meta.owner ? ` · ${meta.owner}` : ''}</div>
        <h1 className="rm-goal">{meta.goal}</h1>
        {meta.window && <div className="rm-hero-meta"><span className="rm-win-chip">{range(meta.window)}</span></div>}
        {meta.definition_of_done_per_ticket && (
          <div className="rm-standard">
            <span className="rm-standard-lab">STANDARD OF PROOF</span>
            <p className="rm-standard-text">{meta.definition_of_done_per_ticket}</p>
          </div>
        )}
      </header>

      <div className="rm-phases">
        {phases.map((p) => (
          <section className="rm-phase" key={p.id}>
            <div className="rm-seal" aria-hidden="true">{p.id}</div>
            <div className="rm-phase-body">
              <div className="rm-phase-head">
                <h2 className="rm-phase-name">{p.name}</h2>
                {p.window && <span className="rm-phase-win">{range(p.window)}</span>}
              </div>
              {p.note && <p className="rm-phase-note">{p.note}</p>}

              <div className="rm-tickets">
                {(p.tickets || []).map((t) => {
                  const { tag, title } = splitTopic(t.topic)
                  return (
                    <button className={`rm-ticket${tag ? ' milestone' : ''}`} key={t.id} type="button"
                      onClick={() => setFocused(t)} title="Open the exhibit sheet">
                      <div className="rm-ticket-top">
                        <span className="rm-code">{t.id}</span>
                        {tag && <span className="rm-tag">{tag}</span>}
                      </div>
                      <div className="rm-ticket-topic">{title}</div>
                      <div className="rm-ticket-foot">
                        {t.deadline && <span className={`rm-due${dueClass(t.deadline)}`}>{dueLabel(t.deadline)}</span>}
                        {t.subtopics?.length > 0 && <span className="rm-count">{t.subtopics.length} steps</span>}
                      </div>
                    </button>
                  )
                })}
              </div>

              {p.exit_exam && (
                <div className="rm-exit">
                  <span className="rm-exit-lab">EXIT EXAM</span>
                  <p className="rm-exit-text">{p.exit_exam}</p>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>

      {(meta.daily_template || meta.rules) && (
        <section className="rm-doctrine">
          {meta.daily_template && (
            <div>
              <div className="s-lab">OPERATING DOCTRINE</div>
              <dl className="rm-deflist">
                {Object.entries(meta.daily_template).map(([k, v]) => (
                  <div className="rm-def" key={k}><dt>{pretty(k)}</dt><dd>{v}</dd></div>
                ))}
              </dl>
            </div>
          )}
          {meta.rules && (
            <div>
              <div className="s-lab">STANDING RULES</div>
              <dl className="rm-deflist">
                {Object.entries(meta.rules).filter(([, v]) => typeof v === 'string').map(([k, v]) => (
                  <div className="rm-def" key={k}><dt>{pretty(k)}</dt><dd>{v}</dd></div>
                ))}
              </dl>
              {meta.rules.banned_this_window?.length > 0 && (
                <div className="rm-banned">
                  <span className="s-lab">INADMISSIBLE THIS WINDOW</span>
                  <div className="rm-banned-chips">
                    {meta.rules.banned_this_window.map((b) => <span className="rm-ban" key={b}>{b}</span>)}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <AnimatePresence>
        {focused && (
          <motion.div className="s-ovl" onClick={() => setFocused(null)}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }}>
            <motion.div className="rm-sheet" onClick={(e) => e.stopPropagation()}
              initial={{ scale: .94, opacity: 0, y: 12 }} animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: .96, opacity: 0 }} transition={{ type: 'spring', stiffness: 320, damping: 26 }}>
              <div className="dk-tab">
                <span>EXHIBIT {focused.id}{sub.tag ? ` — ${sub.tag}` : ''}</span>
                {focused.deadline && <span>{dueLabel(focused.deadline)}</span>}
              </div>
              <div className="rm-sheet-body">
                <h3 className="rm-sheet-topic">{sub.title}</h3>

                {focused.subtopics?.length > 0 && (
                  <>
                    <div className="s-lab">SCOPE</div>
                    <ul className="rm-checklist">{focused.subtopics.map((s) => <li key={s}>{s}</li>)}</ul>
                  </>
                )}

                {focused.resources?.length > 0 && (
                  <>
                    <div className="s-lab" style={{ marginTop: '16px' }}>RESOURCES</div>
                    <ul className="rm-res">{focused.resources.map((r) => <li key={r}>{r}</li>)}</ul>
                  </>
                )}

                {focused.code_proof && (
                  <div className="rm-proof">
                    <span className="s-lab">CODE PROOF</span>
                    <p>{focused.code_proof}</p>
                  </div>
                )}
                {focused.reconstruction_gate && (
                  <div className="rm-gate">
                    <span className="s-lab">RECONSTRUCTION GATE</span>
                    <p>{focused.reconstruction_gate}</p>
                  </div>
                )}

                <div className="rm-sheet-foot">
                  {focused.deadline && <span className="dk-req">Deadline {compact(focused.deadline)} — a scheduling aid, never the completion criterion.</span>}
                  <button className="dk-close" type="button" onClick={() => setFocused(null)}>✕ CLOSE</button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
