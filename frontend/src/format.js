// Presentation-only date/time formatting. All authoritative dates/durations are
// computed server-side; these helpers just render what the UI shows.

const DOW = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

export const todayISO = () => new Date().toISOString().slice(0, 10)

// "FRI 11 JUL 2026"
export function headerDate(d = new Date()) {
  return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}`
}

// "THU 10 JUL" from an ISO YYYY-MM-DD (parsed as local noon to avoid TZ drift)
export function shortDate(iso) {
  if (!iso) return ''
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}`
}

// seconds → "H:MM:SS"
export function clock(sec) {
  const s = Math.max(0, Math.floor(sec))
  const p = (n) => String(n).padStart(2, '0')
  return `${Math.floor(s / 3600)}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`
}

// seconds → "M:SS" (recording display)
export function mmss(sec) {
  const s = Math.max(0, Math.floor(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
