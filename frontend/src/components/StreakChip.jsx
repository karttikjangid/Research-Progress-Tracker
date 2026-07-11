// Today's streak, as a tilted cream chip. `note` is the small line beneath —
// "STREAK INTACT · SINCE 19 JUN" or the broken-state variant.
export default function StreakChip({ day, note }) {
  return (
    <div className="dk-chip">
      <div className="dk-osw" style={{ fontSize: '34px', letterSpacing: '.1em', lineHeight: 1 }}>DAY {day}</div>
      <div className="fs12 mt8" style={{ letterSpacing: '.1em' }}>{note}</div>
    </div>
  )
}
