// This week's theme, as a slightly counter-tilted cream strip beside the chip.
// label defaults to a week-agnostic placeholder for the brief window before
// /api/week resolves — App.jsx derives the real "WEEK N THEME" from
// week.week_of (ISO week number) so it never goes stale like a hardcoded
// week number would.
export default function ThemeStrip({ label = 'WEEK THEME', theme }) {
  return (
    <div className="dk-strip">
      <div className="fs11" style={{ letterSpacing: '.18em', opacity: .65 }}>{label}</div>
      <div className="fs16 fw7 mt8">{theme}</div>
    </div>
  )
}
