// The free-tick strip: self-certified items that carry no weight in the record.
// Each tick is a button; `onToggle` is optional (inert in the static phase).
//
// ticks: [{ label, done, onToggle? }]
export default function TicksStrip({ ticks }) {
  return (
    <div className="dk-ticks">
      <span className="dk-osw fs11" style={{ letterSpacing: '.22em' }}>FREE TICKS</span>
      {ticks.map((t, i) => (
        <button key={i} className="s-tickbtn" onClick={t.onToggle} type="button">
          <span className="fw7">{t.done ? '[×]' : '[  ]'}</span>
          <span className={t.done ? 'dk-off s-strike' : ''}>{t.label}</span>
        </button>
      ))}
    </div>
  )
}
