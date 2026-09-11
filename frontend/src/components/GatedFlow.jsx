import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { post } from '../api'

// The evidence flow remains server-led: drafts only protect work that has not
// been submitted. Submitted artifacts and answers stay authoritative on the
// backend and are never read back from localStorage.
const DRAFT_PREFIX = 'gk:gated-draft:'

function readDraft(key) {
  try { return localStorage.getItem(key) || '' } catch { return '' }
}

function removeDraft(key) {
  try { localStorage.removeItem(key) } catch { /* storage can be unavailable */ }
}

function persistDraft(key, value) {
  try {
    if (value.trim()) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch { /* storage can be unavailable */ }
}

function attemptIdentity(task) {
  return String((task.attempts || 0) + 1)
}

// A question is server-generated and immutable for an attempt. This short
// deterministic identifier keeps a saved answer from leaking into a different
// pending question while avoiding a second copy of its content in the key.
function questionIdentity(question) {
  let hash = 0
  for (let i = 0; i < question.length; i += 1) hash = ((hash << 5) - hash + question.charCodeAt(i)) | 0
  return `${question.length}-${hash >>> 0}`
}

function draftKey(task, kind, question = '') {
  const identity = question ? `:${questionIdentity(question)}` : ''
  return `${DRAFT_PREFIX}${task.id}:${attemptIdentity(task)}:${kind}${identity}`
}

function useDraft(key, initialValue) {
  const [value, setValue] = useState(() => initialValue || readDraft(key))
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setValue(initialValue || readDraft(key))
    setSaved(false)
  }, [key, initialValue])

  useEffect(() => {
    if (!value.trim()) {
      removeDraft(key)
      setSaved(false)
      return undefined
    }
    const timer = window.setTimeout(() => {
      persistDraft(key, value)
      setSaved(true)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [key, value])

  return [value, setValue, saved]
}

// The gated-evidence flow, in the Evidence File aesthetic: paste the artifact →
// the examiner returns one question → submit a final answer → PASS/FAIL verdict.
// Order and immutability are enforced server-side; this only walks the steps.
export default function GatedFlow({ task, onDone }) {
  const pendingQuestion = task.question && !task.answer ? task.question : ''
  const [question, setQuestion] = useState(pendingQuestion)
  const artifactKey = useMemo(() => draftKey(task, 'artifact'), [task])
  const answerKey = useMemo(() => draftKey(task, 'answer', question), [task, question])
  const [artifact, setArtifact, artifactSaved] = useDraft(artifactKey, task.artifact || '')
  const [answer, setAnswer, answerSaved] = useDraft(answerKey, '')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // The parent normally remounts this flow for a new task; this also keeps it
  // safe when a caller reuses the component instance.
  useEffect(() => {
    setQuestion(pendingQuestion)
    setResult(null)
    setErr('')
  }, [task.id, pendingQuestion])

  const submit = (url, body, onOk) => {
    setBusy(true); setErr('')
    post(url, body).then(onOk).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }

  const submitArtifact = () => {
    submit(`/api/tasks/${task.id}/artifact`, { artifact }, (r) => {
      removeDraft(artifactKey)
      setQuestion(r.question)
    })
  }

  const submitAnswer = () => {
    submit(`/api/tasks/${task.id}/answer`, { answer }, (r) => {
      removeDraft(answerKey)
      setResult(r)
    })
  }

  const savedState = question ? answerSaved : artifactSaved
  const closeWithDraft = () => {
    persistDraft(question ? answerKey : artifactKey, question ? answer : artifact)
    onDone()
  }

  return (
    <motion.div className="s-ovl"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }}>
      <motion.div className="s-modal" style={{ maxHeight: '90vh', overflowY: 'auto' }}
        initial={{ scale: .9, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: .95, opacity: 0 }} transition={{ type: 'spring', stiffness: 320, damping: 26 }}>
        <div className="dk-tab"><span>FILE EVIDENCE — {task.title.toUpperCase()}</span><span>{`ATTEMPT ${(task.attempts || 0) + 1} OF 2`}</span></div>
        <div style={{ padding: '20px 26px 26px' }}>
          {err && <p className="s-err" style={{ marginBottom: '14px' }}>{err}</p>}

          {!question && !result && (
            <>
              {task.status === 'failed_once' && task.reason && (
                <div className="s-err" style={{ marginBottom: '14px' }}>
                  Previous attempt failed: {task.reason}
                </div>
              )}
              <div className="dk-req m0">Paste the artifact — the actual proof, diff, or decode notes. Not a topic name; the examiner weighs evidence only.</div>
              <textarea className="s-ta mt12" rows={9} value={artifact} onChange={(e) => setArtifact(e.target.value)} />
              <div className="fx gap12" style={{ marginTop: '16px' }}>
                <button className="s-btn" disabled={busy || !artifact.trim()} type="button" onClick={submitArtifact}>
                  {busy ? 'EXAMINING…' : 'SUBMIT ARTIFACT'}
                </button>
                <button className="s-btn s-btn-dk" onClick={closeWithDraft} type="button" style={{ borderColor: 'rgba(36,31,21,.4)' }}>SAVE & CLOSE</button>
              </div>
            </>
          )}

          {question && !result && (
            <>
              <div className="s-lab">THE EXAMINER ASKS</div>
              <p className="fs14" style={{ lineHeight: 1.55, margin: '10px 0 0' }}>{question}</p>
              <textarea className="s-ta mt16" rows={6} value={answer} onChange={(e) => setAnswer(e.target.value)}
                placeholder="Your answer in your own words — final, no edits after submit." />
              <div className="fx gap12" style={{ marginTop: '16px' }}>
                <button className="s-btn" disabled={busy || !answer.trim()} type="button" onClick={submitAnswer}>
                  {busy ? 'EVALUATING…' : 'SUBMIT ANSWER (FINAL)'}
                </button>
                <button className="s-btn s-btn-dk" disabled={busy} onClick={closeWithDraft} type="button" style={{ borderColor: 'rgba(36,31,21,.4)' }}>SAVE & CLOSE</button>
              </div>
              <div className="dk-req" style={{ marginTop: '10px' }}>Your draft is saved here. The examiner’s question remains pending until you submit a final answer.</div>
            </>
          )}

          {savedState && !result && <p className="s-hint" aria-live="polite" style={{ margin: '10px 0 0', textAlign: 'right' }}>Saved</p>}

          {result && (
            <div className="tc" style={{ padding: '10px 0 4px' }}>
              <div className={`s-bigstamp struck ${result.verdict === 'PASS' ? 'dk-p' : 'dk-f'}`}
                style={result.verdict === 'PASS' ? { borderColor: '#2f6b58', color: '#2f6b58' } : undefined}>
                {result.verdict}
              </div>
              <p className="fs13" style={{ lineHeight: 1.6, margin: '22px 0 0' }}>{result.reason}</p>
              {result.verdict !== 'PASS' && (
                <p className="dk-req" style={{ marginTop: '10px' }}>
                  {result.retry_available
                    ? 'One retry left today — revise the artifact and file again.'
                    : 'Failed twice — this exhibit is locked until tomorrow.'}
                </p>
              )}
              <div style={{ marginTop: '22px' }}>
                <button className="s-btn" onClick={() => onDone(true)} type="button">CLOSE</button>
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
