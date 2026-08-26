import { motion, useReducedMotion } from 'framer-motion'

// MOMENTUM — the streak, made motivating instead of a bare "DAY 0".
// Shows the running streak big, progress toward the next milestone AND toward
// beating your personal best, and a multi-week contribution grid so the arc of
// consistency is visible at a glance. Reads the streak numbers + history the
// Today screen already fetched — no new endpoint.
//
// apple-design: bars fill with a critically-damped spring (no bounce — a data
// update carries no gesture momentum); grid cells settle in; all of it collapses
// to instant under prefers-reduced-motion.

const MILESTONES = [3, 7, 14, 30, 60, 100, 180]
const MILE_NAME = { 3: 'find the groove', 7: 'first full week', 14: 'two weeks', 30: 'a month', 60: 'two months', 100: 'the hundred', 180: 'the whole run' }
const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const CELL_LABEL = {
  clean: 'clean day', broken: 'broken — streak reset',
  grace: 'missed, but grace token saved the streak',
  open: 'logged, not closed', none: 'no file', future: '',
}

const isoLocal = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

// weeks × 7 grid of day-states, ending with the week containing today.
function buildGrid(history, weeks) {
  const map = Object.fromEntries((history || []).map((d) => [d.date, d]))
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const todayISO = isoLocal(today)
  const end = new Date(today); end.setDate(today.getDate() + (6 - today.getDay())) // Saturday
  const start = new Date(end); start.setDate(end.getDate() - (weeks * 7 - 1))       // Sunday
  const cols = []
  for (let w = 0; w < weeks; w++) {
    const col = []
    for (let r = 0; r < 7; r++) {
      const cur = new Date(start); cur.setDate(start.getDate() + w * 7 + r)
      const iso = isoLocal(cur)
      let state = 'none'
      if (iso > todayISO) state = 'future'
      else {
        const d = map[iso]
        if (d) {
          state = d.streak_day ? 'clean'
            : d.grace_used ? 'grace'
            : d.summary_line ? 'broken' : 'open'
        }
      }
      col.push({ iso, state, today: iso === todayISO, dow: DOW[cur.getDay()] })
    }
    cols.push(col)
  }
  return cols
}

export default function Momentum({ streak, closed = false, history }) {
  const reduce = useReducedMotion()
  const current = closed ? 0 : (streak?.current_streak ?? 0)
  const best = streak?.longest_streak ?? 0
  const isBest = current > 0 && current >= best
  const cleanDays = (history || []).filter((d) => d.streak_day).length

  const next = MILESTONES.find((m) => m > current) ?? null
  const prev = [...MILESTONES].reverse().find((m) => m <= current) ?? 0
  const mileFrac = next ? (current - prev) / (next - prev) : 1

  // Beat-your-best bar: how close the current run is to the record.
  const bestFrac = best > 0 ? Math.min(1, current / best) : (current > 0 ? 1 : 0)
  const toBeat = Math.max(0, best - current + 1) // days to SET a new record

  const grid = buildGrid(history, 10)
  const spring = reduce ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.6 }

  return (
    <div className="mo-card">
      <div className="mo-head">
        <div className="mo-numwrap">
          <motion.span className="mo-num" key={current}
            initial={reduce ? false : { scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={reduce ? { duration: 0 } : { type: 'spring', bounce: 0.35, duration: 0.5 }}>
            {current}
          </motion.span>
          <span className="mo-num-lab">DAY{current === 1 ? '' : 'S'}<br />RUNNING</span>
        </div>
        <div className="mo-stats">
          {isBest
            ? <div className="mo-best-tag">{current > best && best > 0 ? 'NEW PERSONAL BEST' : current > 0 ? 'AT YOUR BEST' : ''}</div>
            : <div className="mo-stat"><span className="mo-stat-n">{toBeat}</span> day{toBeat === 1 ? '' : 's'} to beat your best of <span className="mo-stat-n">{best}</span></div>}
          <div className="mo-stat mo-dim">{cleanDays} clean day{cleanDays === 1 ? '' : 's'} on record</div>
        </div>
      </div>

      {/* progress toward beating the record */}
      <div className="mo-meter">
        <div className="mo-meter-lab">
          <span>vs. personal best</span><span>{current} / {Math.max(best, current) || 0}</span>
        </div>
        <div className="mo-track">
          <motion.div className={`mo-fill${isBest ? ' best' : ''}`} initial={false}
            animate={{ scaleX: bestFrac }} transition={spring} />
        </div>
      </div>

      {/* progress toward next milestone */}
      {next && (
        <div className="mo-meter">
          <div className="mo-meter-lab">
            <span>next: {MILE_NAME[next]} ({next})</span><span>{next - current} to go</span>
          </div>
          <div className="mo-track">
            <motion.div className="mo-fill mile" initial={false}
              animate={{ scaleX: mileFrac }} transition={spring} />
          </div>
        </div>
      )}

      <div className="mo-grid-wrap">
        <div className="mo-grid-lab">LAST 10 WEEKS</div>
        <div className="mo-grid">
          {grid.map((col, ci) => (
            <div className="mo-col" key={ci}>
              {col.map((cell) => (
                <motion.div key={cell.iso}
                  className={`mo-cell ${cell.state}${cell.today ? ' today' : ''}`}
                  title={cell.state === 'future' ? '' : `${cell.iso} — ${CELL_LABEL[cell.state]}`}
                  initial={reduce ? false : { opacity: 0, scale: 0.4 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={reduce ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.4, delay: Math.min(0.5, ci * 0.03) }} />
              ))}
            </div>
          ))}
        </div>
        <div className="mo-legend">
          <span><i className="mo-cell clean" /> clean day</span>
          <span><i className="mo-cell grace" /> grace-saved</span>
          <span><i className="mo-cell broken" /> broken</span>
          <span><i className="mo-cell none" /> no file</span>
        </div>
      </div>
    </div>
  )
}
