// The rotated, color-coded ink stamp. PASS = verdigris, FAIL = burgundy.
// `struck` triggers the strike-into-place motion (Phase 2); omitted, the stamp
// simply sits in place as it does in the static export.
export default function VerdictStamp({ verdict, struck = false }) {
  if (verdict !== 'PASS' && verdict !== 'FAIL') return null
  const tone = verdict === 'PASS' ? 'dk-p' : 'dk-f'
  return <div className={`dk-stamp ${tone}${struck ? ' struck' : ''}`}>{verdict}</div>
}
