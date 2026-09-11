import { useState } from 'react'
import { motion } from 'framer-motion'

const choices = [
  {
    id: 'finish',
    title: 'Finish task',
    detail: 'Stop the timer and continue to the evidence check.',
  },
  {
    id: 'paused',
    title: 'Continue later',
    detail: 'Stop here and leave yourself a clean starting point.',
  },
  {
    id: 'stuck',
    title: "I'm stuck",
    detail: 'Record the obstacle and keep the task open.',
  },
]

export default function SessionEndSheet({ task, busy = false, error = '', onCancel, onResolve }) {
  const [choice, setChoice] = useState('')
  const [nextStep, setNextStep] = useState(task?.next_step || '')
  const [blocker, setBlocker] = useState(task?.blocker || '')
  const [tried, setTried] = useState(task?.tried || '')

  const submit = () => {
    if (!choice || busy) return
    onResolve(choice, { next_step: nextStep, blocker, tried })
  }

  return (
    <motion.div className="s-ovl" role="presentation"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.div className="s-modal ux-end-sheet" role="dialog" aria-modal="true"
        aria-labelledby="end-session-title"
        initial={{ scale: .94, opacity: 0, y: 12 }} animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: .96, opacity: 0 }}>
        <div className="dk-tab"><span id="end-session-title">END SESSION</span><span>{task?.title || 'TIMED WORK'}</span></div>
        <div className="ux-sheet-body">
          <p className="fs13 m0 ux-sheet-intro">The timer will stop after you choose what happens next.</p>
          {error && <p className="s-err ux-sheet-error">{error}</p>}
          <div className="ux-end-choices" role="radiogroup" aria-label="What happens next">
            {choices.map((item) => (
              <button key={item.id} type="button" role="radio" aria-checked={choice === item.id}
                className={`ux-choice${choice === item.id ? ' selected' : ''}`}
                onClick={() => setChoice(item.id)}>
                <span className="ux-choice-title">{item.title}</span>
                <span className="ux-choice-detail">{item.detail}</span>
              </button>
            ))}
          </div>

          {choice === 'paused' && (
            <label className="ux-field">
              <span>Next step <span className="s-hint">optional</span></span>
              <textarea className="s-ta" rows={3} value={nextStep}
                onChange={(e) => setNextStep(e.target.value)}
                placeholder="Where should you restart?" autoFocus />
            </label>
          )}
          {choice === 'stuck' && (
            <div className="ux-fields">
              <label className="ux-field">
                <span>What is blocking you?</span>
                <textarea className="s-ta" rows={3} value={blocker}
                  onChange={(e) => setBlocker(e.target.value)} autoFocus />
              </label>
              <label className="ux-field">
                <span>What have you tried? <span className="s-hint">optional</span></span>
                <textarea className="s-ta" rows={2} value={tried}
                  onChange={(e) => setTried(e.target.value)} />
              </label>
            </div>
          )}

          <div className="ux-sheet-actions">
            <button className="s-btn" type="button" onClick={onCancel} disabled={busy}>KEEP TIMER RUNNING</button>
            <button className="s-btn s-fill" type="button" onClick={submit}
              disabled={!choice || busy || (choice === 'stuck' && !blocker.trim())}>
              {busy ? 'ENDING…' : choice === 'finish' ? 'END & CONTINUE' : 'END SESSION'}
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}
