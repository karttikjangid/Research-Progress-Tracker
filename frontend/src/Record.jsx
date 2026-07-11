import { useEffect, useRef, useState } from 'react'
import { get, post, postForm } from './api'
import { mmss, todayISO } from './format'
import EvidenceDoc from './components/EvidenceDoc'

const MIN_SEC = 270 // 4:30 — the server enforces the same floor and deletes shorter takes.

// PHASE 2 — the spoken-shadowing exhibit, wired. Records a single take, uploads
// it, then shows the examiner's audit. Reading the FULL audit is the unlock:
// MARK AS READ is genuinely inert until the report is scrolled to its end.
export default function Record() {
  const [view, setView] = useState('idle') // idle | recording | uploading | report
  const [elapsed, setElapsed] = useState(0)
  const [rec, setRec] = useState(null)
  const [error, setError] = useState('')
  const media = useRef(null)

  // Surface today's existing recording so the audit + its read-gate survive a reload.
  useEffect(() => {
    get('/api/history').then((days) => {
      const r = days.find((d) => d.date === todayISO())?.recordings?.at(-1)
      if (r) { setRec(r); setView('report') }
    }).catch(() => {})
  }, [])

  const start = async () => {
    setError('')
    let stream
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
    catch { setError('Microphone access denied. The examiner needs the recording as evidence.'); return }
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
    const chunks = []
    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.start(1000)
    const t0 = Date.now()
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500)
    media.current = { recorder, chunks, timer, stream }
    setElapsed(0)
    setView('recording')
  }

  const stop = () => {
    const { recorder, chunks, timer, stream } = media.current
    clearInterval(timer)
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      const secs = elapsed
      if (secs < MIN_SEC) {
        setError(`Only ${mmss(secs)} — the floor is 4:30. Take discarded. Begin again.`)
        setView('idle')
        return
      }
      const blob = new Blob(chunks, { type: 'audio/webm' })
      const fd = new FormData()
      fd.append('file', blob, 'monologue.webm')
      setView('uploading')
      postForm('/api/recordings', fd)
        .then((r) => { setRec(r); setView('report') })
        .catch((e) => { setError(e.message); setView('idle') })
    }
    recorder.stop()
  }

  const status = { idle: 'AWAITING SESSION', recording: 'RECORDING', uploading: 'PROCESSING', report: 'ON FILE' }[view]

  return (
    <div className="fx jc" style={{ marginTop: '30px', paddingBottom: '8px' }}>
      <EvidenceDoc tabLeft="EXHIBIT C — SPOKEN SHADOWING AUDIT" tabRight={status} width760>
        <div className="dk-in" style={{ paddingBottom: '24px' }}>
          {error && <p className="s-err" style={{ margin: '16px 0 0' }}>{error}</p>}

          {view === 'idle' && (
            <div className="tc" style={{ padding: '46px 40px 36px' }}>
              <div className="dk-t">A single, unbroken spoken take.</div>
              <div className="dk-req mt8">Minimum 4:30. The examiner audits the recording when you stop; partial takes are filed as-is.</div>
              <div style={{ marginTop: '26px' }}>
                <button className="s-btn" onClick={start} type="button">● BEGIN RECORDING</button>
              </div>
            </div>
          )}

          {view === 'recording' && (
            <div className="tc" style={{ padding: '42px 40px 32px' }}>
              <div className="fx jc ac gap10"><span className="s-recdot"></span><span className="s-lab">RECORDING — SINGLE TAKE</span></div>
              <div className="dk-time" style={{ fontSize: '44px', marginTop: '16px' }}>{mmss(elapsed)}</div>
              <div className="dk-req mt12">{elapsed < MIN_SEC ? `${mmss(MIN_SEC - elapsed)} to the floor. Stopping now discards the take.` : 'Past the floor — stopping files the take for audit.'}</div>
              <div className="mt16">
                <button className={`s-btn${elapsed < MIN_SEC ? ' dis' : ''}`} onClick={stop} type="button">■ STOP &amp; SUBMIT FOR AUDIT</button>
              </div>
            </div>
          )}

          {view === 'uploading' && (
            <div className="tc" style={{ padding: '46px 40px 40px' }}>
              <div className="s-lab">UPLOADING · TRANSCRIBING · AUDITING</div>
              <div className="dk-req mt12">First run downloads the transcription model — this can take minutes.</div>
            </div>
          )}

          {view === 'report' && rec && <AuditReport rec={rec} onViewed={() => setRec({ ...rec, audit_viewed: true })} />}
        </div>
      </EvidenceDoc>
    </div>
  )
}

function AuditReport({ rec, onViewed }) {
  const box = useRef(null)
  const [read, setRead] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const onScroll = () => {
    const el = box.current
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 12) setRead(true)
  }
  // A short audit that doesn't overflow counts as fully read.
  useEffect(() => {
    const el = box.current
    if (el && el.scrollHeight <= el.clientHeight + 12) setRead(true)
  }, [rec])

  const mark = () => {
    setBusy(true); setErr('')
    post(`/api/recordings/${rec.id}/viewed`).then(onViewed).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }

  const viewed = rec.audit_viewed
  return (
    <>
      <div className="fx jb ac mt16">
        <span className="s-lab">AUDIT REPORT · {mmss(rec.duration_sec)} · SESSION {rec.status?.toUpperCase() || 'ON FILE'}</span>
        <span className="s-lab">EXAMINER: LLM</span>
      </div>
      <div className="s-scroll" ref={box} onScroll={onScroll} style={{ whiteSpace: 'pre-wrap' }}>
        {rec.audit || '(audit unavailable)'}
      </div>
      <div className="fx jb ac mt16">
        {err && <p className="s-err m0">{err}</p>}
        {!err && (
          <span className="dk-req m0">
            {viewed ? 'Report read and filed — verbal drill credited for today.'
              : read ? 'Read in full — the unlock is open.'
                : 'Scroll to the end: reading the report is the unlock.'}
          </span>
        )}
        {viewed
          ? <span className="s-vs dk-p">READ</span>
          : <button className={`s-btn${read ? '' : ' dis'}`} onClick={mark} disabled={busy || !read} type="button">MARK AS READ</button>}
      </div>
    </>
  )
}
