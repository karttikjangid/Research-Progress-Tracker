import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { get, post } from '../api'
import '../review-center.css'

const EMPTY_OVERVIEW = { due: [], upcoming: [], completed: [], nextDue: null }

function listFrom(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  if (Array.isArray(value?.reviews)) return value.reviews
  return []
}

// The overview endpoint deliberately contains scheduling metadata only. Keep
// this normalizer liberal so the entry remains compatible with an older server
// (where /due is the only review read endpoint) during a rolling update.
function normalizeOverview(data) {
  const due = listFrom(data?.due ?? data?.reviews_due ?? data?.due_reviews)
  const upcoming = listFrom(data?.upcoming ?? data?.scheduled ?? data?.next)
  const completed = listFrom(data?.completed ?? data?.recent ?? data?.done)
  return {
    due,
    upcoming,
    completed,
    nextDue: data?.next_due ?? data?.nextDue ?? upcoming[0]?.due_date ?? null,
  }
}

function formatDate(value) {
  if (!value) return null
  const date = new Date(`${value}T12:00:00`)
  if (Number.isNaN(date.valueOf())) return value
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function reviewTitle(item) {
  return item?.title || item?.source_title || item?.task_title || 'Learning review'
}

function ReviewOverview({ overview }) {
  const { due, upcoming, completed, nextDue } = overview
  return (
    <div className="review-overview" aria-label="Review schedule">
      <div className="review-overview-row">
        <span>Due</span><strong>{due.length}</strong>
      </div>
      {nextDue && <div className="review-overview-row"><span>Next</span><strong>{formatDate(nextDue)}</strong></div>}
      {upcoming.length > 0 && (
        <div className="review-overview-list">
          <span className="review-overview-label">Upcoming</span>
          {upcoming.slice(0, 3).map((item, index) => (
            <div className="review-overview-item" key={item.id || `${item.due_date}-${index}`}>
              <span>{reviewTitle(item)}</span><span>{formatDate(item.due_date)}</span>
            </div>
          ))}
        </div>
      )}
      {completed.length > 0 && <p className="review-overview-note">{completed.length} completed recently</p>}
    </div>
  )
}

function ReviewSession({ queue, onClose, onComplete, onOpenRecall }) {
  const [index, setIndex] = useState(0)
  const [attempt, setAttempt] = useState('')
  const [revealed, setRevealed] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const item = queue[index]
  const finished = !item

  const reveal = () => {
    if (!item || busy) return
    setBusy(true); setErr('')
    post(`/api/reviews/${item.id}/reveal`)
      .then(setRevealed)
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const grade = (gradeName) => {
    if (!item || busy) return
    setBusy(true); setErr('')
    post(`/api/reviews/${item.id}/grade`, { grade: gradeName })
      .then(setResult)
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const next = () => {
    if (index + 1 >= queue.length) {
      onComplete()
      return
    }
    setIndex((current) => current + 1)
    setAttempt('')
    setRevealed(null)
    setResult(null)
    setErr('')
  }

  return (
    <motion.div className="s-ovl" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }}>
      <motion.section className="s-modal review-session" role="dialog" aria-modal="true" aria-labelledby="review-session-title"
        initial={{ scale: .94, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: .96, opacity: 0 }}
        transition={{ type: 'spring', stiffness: 320, damping: 26 }}>
        <div className="dk-tab"><span id="review-session-title">LEARNING REVIEW</span><span>{finished ? `${queue.length} COMPLETE` : `${index + 1} OF ${queue.length}`}</span></div>
        <div className="review-session-body">
          {err && <p className="s-err" role="alert">{err}</p>}
          {finished ? (
            <div className="review-result review-result-done">
              <div className="s-bigstamp dk-p" style={{ borderColor: '#2f6b58', color: '#2f6b58' }}>DONE</div>
              <p>You completed this review session.</p>
              <button className="s-btn" type="button" onClick={onClose}>CLOSE</button>
            </div>
          ) : (
            <>
              <div className="review-prompt-label">RECALL BEFORE REVEALING</div>
              <h2 className="review-title">{reviewTitle(item)}</h2>
              {item.overdue && <p className="review-overdue">Overdue since {formatDate(item.due_date)}</p>}

              {!revealed && !result && (
                <>
                  <label className="fs12" htmlFor={`recall-attempt-${item.id}`}>What can you recall? <span className="s-hint">Optional</span></label>
                  <textarea id={`recall-attempt-${item.id}`} className="s-ta review-attempt" rows={5} value={attempt}
                    onChange={(event) => setAttempt(event.target.value)} placeholder="Try to explain it before looking at the material." />
                  <div className="review-session-actions">
                    <button className="s-btn" type="button" disabled={busy} onClick={reveal}>{busy ? 'OPENING…' : 'REVEAL MATERIAL'}</button>
                    <button className="s-btn s-btn-dk" type="button" disabled={busy} onClick={onClose}>CLOSE</button>
                  </div>
                </>
              )}

              {revealed && !result && (
                <>
                  {attempt.trim() && <div className="review-attempt-saved"><span className="s-lab">YOUR RECALL</span><p>{attempt}</p></div>}
                  <div className="review-reveal">
                    <span className="s-lab">SAVED MATERIAL</span>
                    <p className="review-artifact">{revealed.artifact || 'No saved artifact was found.'}</p>
                    {revealed.question && <p className="review-question"><strong>Question:</strong> {revealed.question}</p>}
                    {revealed.answer && <p className="review-answer"><strong>Answer:</strong> {revealed.answer}</p>}
                  </div>
                  <div className="review-grade" aria-label="Rate your recall">
                    <p className="fs12">How well did you recall it?</p>
                    <div className="review-grade-actions">
                      <button className="s-mini-btn" type="button" disabled={busy} onClick={() => grade('recalled')}>RECALLED</button>
                      <button className="s-mini-btn" type="button" disabled={busy} onClick={() => grade('partial')}>PARTLY</button>
                      <button className="s-mini-btn review-forgot" type="button" disabled={busy} onClick={() => grade('forgot')}>FORGOT</button>
                    </div>
                  </div>
                </>
              )}

              {result && (
                <div className="review-result" aria-live="polite">
                  <div className="s-bigstamp struck" style={{ borderColor: '#2f6b58', color: '#2f6b58' }}>SAVED</div>
                  {result.retired
                    ? <p>This item has completed its scheduled review cycle.</p>
                    : <p>Next review: <strong>{formatDate(result.next_due) || 'scheduled soon'}</strong>.</p>}
                  {result.recall_task_id && (
                    <div className="review-recall-task">
                      <p>A recall task was added so you can rebuild this explanation.</p>
                      {onOpenRecall && <button className="s-mini-btn" type="button" onClick={() => onOpenRecall(result.recall_task_id)}>OPEN RECALL TASK</button>}
                    </div>
                  )}
                  <button className="s-btn" type="button" onClick={next}>{index + 1 < queue.length ? 'NEXT REVIEW' : 'FINISH REVIEWS'}</button>
                </div>
              )}
            </>
          )}
        </div>
      </motion.section>
    </motion.div>
  )
}

// Standalone component for Today. The parent may pass onChange to refresh its
// task/streak state and onOpenRecall(recallTaskId) to focus a newly-created task.
export default function ReviewCenter({ onChange, onOpenRecall }) {
  const [overview, setOverview] = useState(EMPTY_OVERVIEW)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      setOverview(normalizeOverview(await get('/api/reviews/overview')))
    } catch (overviewError) {
      // This fallback makes the newly-visible entry safe to ship before the
      // overview endpoint reaches every local server; it only knows due work.
      try {
        const due = await get('/api/reviews/due')
        setOverview({ ...EMPTY_OVERVIEW, due })
      } catch (dueError) {
        setError(dueError.message || overviewError.message)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  const dueSummary = useMemo(() => overview.due.length, [overview.due.length])
  const nextDate = formatDate(overview.nextDue)

  const closeSession = () => setReviewing(false)
  const completeSession = () => {
    setReviewing(false)
    load()
    onChange?.()
  }

  return (
    <>
      <section className="s-card review-center" aria-label="Learning reviews">
        <div className="review-entry">
          <div>
            <div className="s-lab">LEARNING REVIEWS</div>
            {loading ? <p className="review-entry-copy">Checking your schedule…</p>
              : error ? <p className="review-entry-copy review-error">Review schedule is unavailable.</p>
                : dueSummary > 0 ? <p className="review-entry-copy">{dueSummary} {dueSummary === 1 ? 'review' : 'reviews'} due{overview.due.some((item) => item.overdue) ? ' · includes overdue work' : ''}</p>
                  : <p className="review-entry-copy">Nothing due{nextDate ? ` · next ${nextDate}` : ''}</p>}
          </div>
          {dueSummary > 0 && <button className="s-mini-btn" type="button" disabled={loading} onClick={() => setReviewing(true)}>START REVIEW</button>}
        </div>
        {error && <button className="review-retry" type="button" onClick={load}>TRY AGAIN</button>}
        <button className="review-disclosure" type="button" aria-expanded={expanded} onClick={() => setExpanded((isExpanded) => !isExpanded)}>
          <span>{expanded ? 'Hide schedule' : 'View schedule'}</span><span aria-hidden="true">{expanded ? '−' : '+'}</span>
        </button>
        {expanded && <ReviewOverview overview={overview} />}
      </section>

      <AnimatePresence>
        {reviewing && <ReviewSession queue={overview.due} onClose={closeSession} onComplete={completeSession} onOpenRecall={onOpenRecall} />}
      </AnimatePresence>
    </>
  )
}
