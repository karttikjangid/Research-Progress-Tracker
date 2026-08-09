import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get, post, postForm } from './api'
import { mmss, todayISO } from './format'
import EvidenceDoc from './components/EvidenceDoc'

const MIN_SEC = 270          // 4:30 floor — the server enforces the same.
const VISIBLE_SEC = 6        // seconds of waveform in view
const PLAYHEAD_FRAC = 0.62   // where "now" sits across the canvas

const p2 = (n) => String(n).padStart(2, '0')
const fmtCenti = (sec) => `${p2(Math.floor(sec / 60))}:${p2(Math.floor(sec % 60))}.${p2(Math.floor((sec % 1) * 100))}`
const fmtRuler = (s) => `${p2(Math.floor(s / 60))}:${p2(s % 60)}`

// PHASE 2 — the spoken-shadowing recorder, restyled after a clean voice-recorder
// (live scrolling waveform + ruler + playhead, centisecond timer, circular dial)
// but on the cream evidence document in the Evidence File palette. The underlying
// capture → upload → transcribe → audit flow is unchanged.
export default function Record() {
  const [view, setView] = useState('idle') // idle | recording | uploading | report
  const [rec, setRec] = useState(null)
  const [error, setError] = useState('')

  const loadLatest = () =>
    get('/api/history').then((days) => {
      const r = days.find((d) => d.date === todayISO())?.recordings?.at(-1)
      if (r) { setRec(r); setView('report') }
      return r
    })

  useEffect(() => { loadLatest().catch(() => {}) }, [])

  const status = { idle: 'AWAITING SESSION', recording: 'RECORDING', uploading: 'PROCESSING', report: 'ON FILE' }[view]

  return (
    <div className="fx jc" style={{ marginTop: '30px', paddingBottom: '8px' }}>
      <EvidenceDoc tabLeft="EXHIBIT C — SPOKEN SHADOWING AUDIT" tabRight={status} width760>
        <div className="dk-in" style={{ paddingBottom: '20px' }}>
          {error && <p className="s-err" style={{ margin: '16px 0 0' }}>{error}</p>}
          {(view === 'idle' || view === 'recording') && (
            <Recorder view={view} setView={setView} setRec={setRec} setError={setError} />
          )}
          {view === 'uploading' && (
            <div className="tc" style={{ padding: '46px 40px 40px' }}>
              <div className="s-lab">UPLOADING · TRANSCRIBING · AUDITING</div>
              <div className="dk-req mt12">Transcribing your take and running the audit — this can take up to a minute.</div>
            </div>
          )}
          {view === 'report' && rec && (
            <AuditReport rec={rec} onViewed={() => setRec({ ...rec, audit_viewed: true })} onRetried={setRec} />
          )}
        </div>
      </EvidenceDoc>
    </div>
  )
}

// Live feedback on the 4:30 floor while recording — previously the only way
// to learn a take was too short was to stop and get the "Be Brave" discard
// notice after the fact, discarding real spoken minutes. Written straight to
// the DOM (like the timer) rather than React state, so it doesn't force a
// re-render every animation frame.
const floorNote = (el, now) => {
  if (!el) return
  const remain = MIN_SEC - now
  if (remain > 0) {
    el.textContent = `${fmtRuler(Math.ceil(remain))} short of the 4:30 floor`
    el.style.color = ''
  } else {
    el.textContent = '4:30 floor reached — safe to stop anytime'
    el.style.color = '#2f6b58'
  }
}

function Recorder({ view, setView, setRec, setError }) {
  const canvasRef = useRef(null)
  const timerRef = useRef(null)
  const floorRef = useRef(null)
  const eng = useRef(null)
  const [notice, setNotice] = useState(null) // { short: "M:SS" } when a take was too short
  const recording = view === 'recording'

  // Draw the static frame (ruler + playhead) whenever the canvas mounts.
  useEffect(() => {
    if (canvasRef.current) { fitCanvas(canvasRef.current); draw(canvasRef.current, [], 0) }
  }, [view])
  // Tear down audio if the panel unmounts mid-take.
  useEffect(() => () => teardown(eng.current), [])

  const loop = () => {
    const E = eng.current
    if (!E) return
    const now = (performance.now() - E.start) / 1000
    E.elapsed = now
    E.analyser.getByteTimeDomainData(E.data)
    let sum = 0
    for (let i = 0; i < E.data.length; i++) { const v = (E.data[i] - 128) / 128; sum += v * v }
    E.samples.push({ t: now, amp: Math.min(1, Math.sqrt(sum / E.data.length) * 3.2) })
    const cutoff = now - VISIBLE_SEC * 2
    while (E.samples.length && E.samples[0].t < cutoff) E.samples.shift()
    if (canvasRef.current) draw(canvasRef.current, E.samples, now)
    if (timerRef.current) timerRef.current.textContent = fmtCenti(now)
    floorNote(floorRef.current, now)
    E.raf = requestAnimationFrame(loop)
  }

  const start = async () => {
    setError(''); setNotice(null)
    let stream
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
    catch { setError('Microphone access denied. The examiner needs the recording as evidence.'); return }
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    ctx.createMediaStreamSource(stream).connect(analyser)
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
    const chunks = []
    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.start(1000)
    eng.current = { stream, ctx, analyser, data: new Uint8Array(analyser.fftSize), recorder, chunks, samples: [], start: performance.now(), raf: 0, elapsed: 0 }
    setView('recording')
    loop()
  }

  // Stop the take and submit it — used by both the dial and SAVE. A take under
  // the 4:30 floor can't be filed, so it's discarded with the "Be Brave" notice.
  const submit = () => {
    const E = eng.current
    if (!E) return
    E.recorder.onstop = () => {
      const secs = E.elapsed
      teardown(E)
      eng.current = null
      if (secs < MIN_SEC) {
        setNotice({ short: mmss(Math.floor(secs)) })
        setView('idle'); return
      }
      const fd = new FormData()
      fd.append('file', new Blob(E.chunks, { type: 'audio/webm' }), 'monologue.webm')
      setView('uploading')
      postForm('/api/recordings', fd).then((r) => { setRec(r); setView('report') })
        .catch((e) => {
          setError(e.message)
          // A rejected upload (garbage audio / under 4:30) never creates a Recording
          // row — no id, nothing to recover, back to idle. A failure inside _process
          // (transcription/audit) does create a row; the audio is already safely on
          // disk (backend/main.py's durability note), and the server hands back its
          // id via X-Recording-Id so the report view can offer a retry instead of
          // silently dropping the take and forcing a full 5-minute re-record.
          if (e.recordingId) {
            get(`/api/recordings/${e.recordingId}`).then((r) => { setRec(r); setView('report') })
              .catch(() => setView('idle'))
          } else {
            setView('idle')
          }
        })
    }
    E.recorder.stop()
  }

  // The ✕ is a hard reset, not a submit: abandon any take in progress, tear down
  // audio, and return every control to its pristine idle state — timer, waveform,
  // notice, error. No "too short" notice; this is a deliberate discard.
  const reset = () => {
    const E = eng.current
    eng.current = null
    if (E) {
      E.recorder.ondataavailable = null
      E.recorder.onstop = null
      try { E.recorder.stop() } catch { /* recorder never started */ }
      teardown(E)
    }
    setNotice(null); setError('')
    if (timerRef.current) timerRef.current.textContent = fmtCenti(0)
    if (floorRef.current) floorNote(floorRef.current, 0)
    if (canvasRef.current) draw(canvasRef.current, [], 0)
    setView('idle')
  }

  return (
    <div className="rec-stage">
      <div className="rec-top">
        <button className="rec-x" onClick={reset} type="button" title="Discard the take and reset">✕</button>
        <button className="rec-save" onClick={submit} type="button" disabled={!recording}>SAVE &amp; SUBMIT</button>
      </div>
      <div className="rec-wave"><canvas ref={canvasRef} className="rec-canvas"></canvas></div>
      <div className="rec-timer" ref={timerRef}>00:00.00</div>
      {recording && <div className="fs12 tc" style={{ marginTop: '-8px', marginBottom: '8px' }} ref={floorRef}>4:30 short of the 4:30 floor minimum</div>}
      <Dial recording={recording} onClick={recording ? submit : start} />

      <AnimatePresence>
        {notice && !recording && (
          <motion.div className="rec-notice"
            initial={{ opacity: 0, scale: .82, y: 6 }} animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: .9 }} transition={{ type: 'spring', stiffness: 380, damping: 20 }}>
            <div className="rec-notice-h">Be Brave — Speak More</div>
            <div className="rec-notice-s">Only {notice.short} of the 4:30 minimum. The take was discarded — begin again.</div>
          </motion.div>
        )}
      </AnimatePresence>

      {!notice && (
        <div className="rec-hint">
          {recording ? 'Recording a single take — minimum 4:30. Tap the dial to stop and submit.'
            : 'Tap the dial to begin a single, unbroken spoken take. Minimum 4:30; partial takes are filed as-is.'}
        </div>
      )}
    </div>
  )
}

function Dial({ recording, onClick }) {
  const ticks = [45, 135, 225, 315]
  return (
    <svg className={`rec-dial${recording ? ' spin' : ''}`} viewBox="0 0 200 200" onClick={onClick} role="button" aria-label={recording ? 'Stop' : 'Record'}>
      <circle cx="100" cy="100" r="92" fill="none" stroke="#241f15" strokeWidth="1.5" />
      {ticks.map((a) => {
        const rad = (a * Math.PI) / 180
        return <line key={a} x1={100 + 92 * Math.cos(rad)} y1={100 + 92 * Math.sin(rad)}
          x2={100 + 80 * Math.cos(rad)} y2={100 + 80 * Math.sin(rad)} stroke="#241f15" strokeWidth="1.5" />
      })}
      <circle cx="100" cy="100" r="36" fill="rgba(36,31,21,.08)" />
      <circle cx="100" cy="100" r="14" fill="#93261f" className={recording ? 'rec-dot-anim' : ''} />
    </svg>
  )
}

function fitCanvas(c) {
  const dpr = window.devicePixelRatio || 1
  const r = c.getBoundingClientRect()
  c.width = Math.max(1, r.width * dpr)
  c.height = Math.max(1, r.height * dpr)
  c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0)
}

function draw(c, samples, now) {
  const dpr = window.devicePixelRatio || 1
  const ctx = c.getContext('2d')
  const w = c.width / dpr, h = c.height / dpr
  ctx.clearRect(0, 0, w, h)
  const pps = w / VISIBLE_SEC, playX = w * PLAYHEAD_FRAC, midY = h * 0.44
  // ruler
  ctx.strokeStyle = 'rgba(36,31,21,.18)'; ctx.fillStyle = 'rgba(36,31,21,.45)'
  ctx.lineWidth = 1; ctx.font = '10px "Courier Prime", monospace'; ctx.textAlign = 'center'
  const leftT = now - playX / pps, rightT = now + (w - playX) / pps
  for (let s = Math.ceil(leftT); s <= Math.floor(rightT); s++) {
    if (s < 0) continue
    const x = playX + (s - now) * pps
    ctx.beginPath(); ctx.moveTo(x, h - 16); ctx.lineTo(x, h - 10); ctx.stroke()
    ctx.fillText(fmtRuler(s), x, h - 1)
  }
  // waveform
  ctx.strokeStyle = '#93261f'; ctx.lineWidth = 2
  for (const sm of samples) {
    const x = playX + (sm.t - now) * pps
    if (x < 0 || x > w) continue
    const bh = Math.max(1.5, sm.amp * h * 0.34)
    ctx.beginPath(); ctx.moveTo(x, midY - bh); ctx.lineTo(x, midY + bh); ctx.stroke()
  }
  // playhead
  ctx.strokeStyle = '#93261f'; ctx.lineWidth = 1.5
  ctx.beginPath(); ctx.moveTo(playX, 0); ctx.lineTo(playX, h - 18); ctx.stroke()
  ctx.fillStyle = '#93261f'; ctx.beginPath(); ctx.arc(playX, h - 18, 3, 0, Math.PI * 2); ctx.fill()
}

function teardown(E) {
  if (!E) return
  cancelAnimationFrame(E.raf)
  try { E.ctx.close() } catch { /* already closed */ }
  E.stream.getTracks().forEach((t) => t.stop())
}

function AuditReport({ rec, onViewed, onRetried }) {
  const box = useRef(null)
  const [read, setRead] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [retrying, setRetrying] = useState(false)
  const [retryErr, setRetryErr] = useState('')

  // uploaded | transcription_failed | audit_failed | done (backend/db.py). Anything
  // short of 'done' has no real audit text to read, so offer a retry instead of the
  // scroll-to-unlock flow — the previous version funneled the placeholder text
  // ("audit file missing") through MARK AS READ, which the backend correctly 409s.
  const failed = rec.status && rec.status !== 'done'

  const onScroll = () => {
    const el = box.current
    if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 12) setRead(true)
  }
  useEffect(() => {
    const el = box.current
    if (el && el.scrollHeight <= el.clientHeight + 12) setRead(true)
  }, [rec])

  const mark = () => {
    setBusy(true); setErr('')
    post(`/api/recordings/${rec.id}/viewed`).then(onViewed).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }

  const retry = () => {
    setRetrying(true); setRetryErr('')
    post(`/api/recordings/${rec.id}/retry`).then(onRetried).catch((e) => setRetryErr(e.message)).finally(() => setRetrying(false))
  }

  const viewed = rec.audit_viewed
  return (
    <>
      <div className="fx jb ac mt16">
        <span className="s-lab">AUDIT REPORT · {mmss(rec.duration_sec)} · {rec.status?.toUpperCase() || 'ON FILE'}</span>
        <span className="s-lab">EXAMINER: LLM</span>
      </div>
      <div className="s-scroll" ref={box} onScroll={onScroll} style={{ whiteSpace: 'pre-wrap' }}>
        {rec.audit || '(audit unavailable)'}
      </div>
      <div className="fx jb ac mt16">
        {failed ? (
          <>
            <span className="s-err m0">
              {retryErr || (rec.status === 'transcription_failed'
                ? 'Transcription failed — no report was generated.'
                : 'The audit step failed after transcription — no report was generated.')}
            </span>
            <button className="s-btn" onClick={retry} disabled={retrying} type="button">
              {retrying ? 'RETRYING…' : 'RETRY AUDIT'}
            </button>
          </>
        ) : (
          <>
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
          </>
        )}
      </div>
    </>
  )
}
