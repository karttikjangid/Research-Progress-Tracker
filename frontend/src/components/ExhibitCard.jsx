import { motion } from 'framer-motion'
import VerdictStamp from './VerdictStamp'

// One specimen card in the fan. The root is a motion element so the parent can
// deal it in, lift it on hover, and pull it to focus. Content is unchanged from
// the export; `footer` (action row) and the larger type only show when focused.
//
// Props:
//   letter, statusLabel, title, req, reason, verdict — card content
//   struck    bool — animate the stamp in
//   focused   bool — this card is the one pulled forward
//   children  the session-area node
//   footer    action row shown only when focused
//   onClick   focus this card
//   motionProps  spread onto the motion.div (initial/animate/transition/style)
export default function ExhibitCard({
  letter, statusLabel, title, req, reason, verdict = null,
  struck = false, focused = false, children, footer, onClick, motionProps = {},
}) {
  return (
    <motion.div className={`dk-card${focused ? ' focused' : ''}`} onClick={onClick} {...motionProps}>
      <div className="dk-tab"><span>EXHIBIT {letter}</span><span>{statusLabel}</span></div>
      <div className="dk-in">
        <div className="dk-t">{title}</div>
        <div className="dk-req">{req}</div>
        <div className="dk-dash"></div>
        {children}
        <div className="dk-dash"></div>
        <div className="dk-reason">{reason}</div>
        {focused && footer && <div className="dk-actions">{footer}</div>}
      </div>
      <VerdictStamp verdict={verdict} struck={struck} />
    </motion.div>
  )
}
