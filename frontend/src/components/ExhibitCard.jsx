import VerdictStamp from './VerdictStamp'

// One tilted specimen card in the fan. Renders either a resolved exhibit (with a
// PASS/FAIL stamp) or an open one (session-running block, no verdict yet).
//
// Props:
//   letter       'A' | 'B' | 'C'                      — exhibit label
//   posClass     'dk-c1' | 'dk-c2' | 'dk-c3'          — fan position + tilt
//   statusLabel  'RESOLVED' | 'OPEN'                  — tab right-hand text
//   title, req   the task and its evidence requirement
//   sessionLabel 'SESSION' | 'SESSION RUNNING'
//   time         session duration string
//   reason       one-line examiner reason
//   verdict      'PASS' | 'FAIL' | null
//   inSession    bool — show the IN SESSION badge instead of a plain session line
//   struck       bool — animate the stamp in (Phase 2)
//   onClick      optional — open the gated flow for this exhibit (Phase 2)
//   children     optional — a custom session-area node; overrides sessionLabel/time
export default function ExhibitCard({
  letter, posClass, statusLabel, title, req,
  sessionLabel = 'SESSION', time, reason, verdict = null,
  inSession = false, struck = false, onClick, children,
}) {
  const clickable = typeof onClick === 'function'
  return (
    <div
      className={`dk-card ${posClass}`}
      onClick={onClick}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } } : undefined}
      style={clickable ? { cursor: 'pointer' } : undefined}
    >
      <div className="dk-tab"><span>EXHIBIT {letter}</span><span>{statusLabel}</span></div>
      <div className="dk-in">
        <div className="dk-t">{title}</div>
        <div className="dk-req">{req}</div>
        <div className="dk-dash"></div>
        {children ? children : inSession ? (
          <div className="fx jb ac">
            <div>
              <div className="s-lab">{sessionLabel}</div>
              <div className="dk-time mt8">{time}</div>
            </div>
            <span className="dk-sess">IN SESSION</span>
          </div>
        ) : (
          <>
            <div className="s-lab">{sessionLabel}</div>
            <div className="dk-time mt8">{time}</div>
          </>
        )}
        <div className="dk-dash"></div>
        <div className="dk-reason">{reason}</div>
      </div>
      <VerdictStamp verdict={verdict} struck={struck} />
    </div>
  )
}
