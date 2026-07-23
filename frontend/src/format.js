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

// ISO-8601 week number for a YYYY-MM-DD date (parsed as local noon to avoid
// TZ drift). Week 1 is the week containing the year's first Thursday.
export function isoWeekNumber(iso) {
  if (!iso) return null
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return null
  const thursday = new Date(d)
  thursday.setDate(d.getDate() - ((d.getDay() + 6) % 7) + 3)
  const firstThursday = new Date(thursday.getFullYear(), 0, 4)
  firstThursday.setDate(firstThursday.getDate() - ((firstThursday.getDay() + 6) % 7) + 3)
  return 1 + Math.round((thursday - firstThursday) / (7 * 86400000))
}

// Whole days from today (local) to an ISO YYYY-MM-DD. Negative = past due.
// Both ends pinned to local noon so DST/timezone never shifts the day count.
export function daysUntil(iso) {
  if (!iso) return null
  const target = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(target.getTime())) return null
  const now = new Date()
  const noonToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12)
  return Math.round((target - noonToday) / 86400000)
}

// "due in 6 days" / "due tomorrow" / "due today" / "3 days overdue"
export function dueLabel(iso) {
  const d = daysUntil(iso)
  if (d == null) return ''
  if (d === 0) return 'due today'
  if (d === 1) return 'due tomorrow'
  if (d === -1) return '1 day overdue'
  return d > 0 ? `due in ${d} days` : `${-d} days overdue`
}
