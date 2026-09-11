import { motion } from 'framer-motion'
import { headerDate } from '../format'

// The close-of-day modal. Confirmation (verdict summary + consequence) then the
// closed acknowledgement with the big FILE CLOSED stamp, which strikes in.
//
// Props:
//   closed       bool — which state to show
//   loading      bool — summary still loading
//   error        string — load/close error, if any
//   rows         [{ label, verdict, tone, actionLabel?, onAction?, actionBusy? }]
//   tickCount, tickTotal — free ticks done / total
//   warnings     string[] — cold factual notices about what closing will record
//                (open session, verbal MISSED, TASTELOG MISSING); each rendered
//                in the same s-err style. One mechanism for all close-time flags.
//   consequence  sentence describing what closing records
//   closedNote   acknowledgement html shown once closed
//   resolveActions [{label, onClick, busy?}] — direct routes for loose ends
//   onKeepWorking, onConfirmClose, onDone — handlers
export default function CloseFileModal({
  closed, loading = false, error = '', rows = [], tickCount = 0, tickTotal = 0,
  warnings = [], consequence, closedNote, resolveActions = [], onKeepWorking, onConfirmClose, onDone,
}) {
  return (
    <motion.div className="s-ovl"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }}>
      <motion.div className="s-modal"
        initial={{ scale: .9, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: .95, opacity: 0 }} transition={{ type: 'spring', stiffness: 320, damping: 26 }}>
        <div className="dk-tab"><span>CLOSE OF DAY</span><span>{headerDate()}</span></div>
        {!closed ? (
          <div style={{ padding: '20px 26px 26px' }}>
            {error && <p className="s-err" style={{ marginBottom: '14px' }}>{error}</p>}
            {loading && <p className="dk-req m0">Assembling today’s exhibits…</p>}
            {!loading && rows.length === 0 && !error && (
              <p className="dk-req m0" style={{ marginBottom: '8px' }}>No gated exhibits filed today.</p>
            )}
            {rows.map((r, i) => (
              <div className="s-srow ux-close-row" key={i}>
                <span className="ux-close-label">{r.label}</span>
                <span className="fx ac gap8 ux-close-status">
                  <span className={`s-vs ${r.tone || ''}`.trim()}>{r.verdict}</span>
                  {r.actionLabel && (
                    <button className="s-mini-btn ux-row-action" type="button" onClick={r.onAction}
                      disabled={r.actionBusy}>{r.actionLabel}</button>
                  )}
                </span>
              </div>
            ))}
            {(rows.length > 0 || tickTotal > 0) && (
              <div className="s-srow" style={{ borderBottom: 'none' }}>
                <span>FREE TICKS</span>
                <span className="dk-off">{tickCount} of {tickTotal} — carry no weight</span>
              </div>
            )}
            {!loading && warnings.map((w, i) => (
              <p className="s-err" key={i} style={{ lineHeight: 1.6, margin: '8px 0 0' }}>{w}</p>
            ))}
            {!loading && resolveActions.length > 0 && (
              <div className="ux-close-actions" aria-label="Resolve unfinished work">
                {resolveActions.map((a) => (
                  <button className="s-mini-btn" type="button" key={a.label}
                    disabled={a.busy} onClick={a.onClick}>{a.busy ? 'WORKING…' : a.label}</button>
                ))}
              </div>
            )}
            {!loading && (
              <p className="fs13" style={{ lineHeight: 1.6, margin: '8px 0 0' }}>{consequence}</p>
            )}
            <div className="fx jb" style={{ marginTop: '26px' }}>
              <button className="s-btn" onClick={onKeepWorking} type="button">KEEP WORKING</button>
              <button className="s-btn s-fill" onClick={onConfirmClose} type="button" disabled={loading}>CLOSE THE FILE</button>
            </div>
          </div>
        ) : (
          <div className="tc" style={{ padding: '38px 26px 30px' }}>
            <div className="s-bigstamp struck">FILE CLOSED</div>
            <p className="fs13" style={{ lineHeight: 1.7, margin: '26px 0 0' }}
              dangerouslySetInnerHTML={{ __html: closedNote }} />
            <div style={{ marginTop: '26px' }}>
              <button className="s-btn" onClick={onDone} type="button">DONE</button>
            </div>
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}
