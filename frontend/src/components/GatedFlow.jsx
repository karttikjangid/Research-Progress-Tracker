import { useState } from 'react'
import { motion } from 'framer-motion'
import { post } from '../api'

// The gated-evidence flow, in the Evidence File aesthetic: paste the artifact →
// the examiner returns one question → submit a final answer → PASS/FAIL verdict.
// Order and immutability are enforced server-side; this only walks the steps.
//
// Restores a pending (unanswered) question after a reload — the backend refuses
// a fresh artifact while one is pending.
export default function GatedFlow({ task, onDone }) {
  const [artifact, setArtifact] = useState(task.artifact || '')
  const [question, setQuestion] = useState(task.question && !task.answer ? task.question : '')
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = (url, body, onOk) => {
    setBusy(true); setErr('')
    post(url, body).then(onOk).catch((e) => setErr(e.message)).finally(() => setBusy(false))
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
              <div className="dk-req m0">Paste the artifact — the actual proof, diff, or decode notes. Not a topic name; the examiner weighs evidence only.</div>
              <textarea className="s-ta mt12" rows={9} value={artifact} onChange={(e) => setArtifact(e.target.value)} />
              <div className="fx gap12" style={{ marginTop: '16px' }}>
                <button className="s-btn" disabled={busy} type="button"
                  onClick={() => submit(`/api/tasks/${task.id}/artifact`, { artifact }, (r) => setQuestion(r.question))}>
                  {busy ? 'EXAMINING…' : 'SUBMIT ARTIFACT'}
                </button>
                <button className="s-btn s-btn-dk" onClick={() => onDone()} type="button" style={{ borderColor: 'rgba(36,31,21,.4)' }}>CANCEL</button>
              </div>
            </>
          )}

          {question && !result && (
            <>
              <div className="s-lab">THE EXAMINER ASKS</div>
              <p className="fs14" style={{ lineHeight: 1.55, margin: '10px 0 0' }}>{question}</p>
              <textarea className="s-ta mt16" rows={6} value={answer} onChange={(e) => setAnswer(e.target.value)}
                placeholder="Your answer in your own words — final, no edits after submit." />
              <div className="fx" style={{ marginTop: '16px' }}>
                <button className="s-btn" disabled={busy || !answer.trim()} type="button"
                  onClick={() => submit(`/api/tasks/${task.id}/answer`, { answer }, setResult)}>
                  {busy ? 'EVALUATING…' : 'SUBMIT ANSWER (FINAL)'}
                </button>
              </div>
              <div className="dk-req" style={{ marginTop: '10px' }}>No cancel at this stage — leaving files the question as pending.</div>
            </>
          )}

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
