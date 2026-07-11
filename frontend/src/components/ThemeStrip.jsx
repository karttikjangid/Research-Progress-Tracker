// This week's theme, as a slightly counter-tilted cream strip beside the chip.
export default function ThemeStrip({ label = 'WEEK 28 THEME', theme }) {
  return (
    <div className="dk-strip">
      <div className="fs11" style={{ letterSpacing: '.18em', opacity: .65 }}>{label}</div>
      <div className="fs16 fw7 mt8">{theme}</div>
    </div>
  )
}
