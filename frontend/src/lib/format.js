export function fmtNum(value, digits) {
  if (value === null || value === undefined || value === '') return '—'
  if (!Number.isFinite(Number(value))) return String(value)
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits ?? 8 }).format(Number(value))
}
export const fmtUnit = unit => ({ 'mA/cm2': 'мА/см²', 'mW/cm2': 'мВт/см²', cm2: 'см²', V: 'В', nm: 'нм', fraction: 'доля' }[unit] || unit || '')
export const fmtValue = (v, unit) => `${fmtNum(v)}${unit ? ` ${fmtUnit(unit)}` : ''}`
export const fmtResult = r => fmtValue(r?.metric_value, r?.metric_unit)
export const fmtDate = value => value ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value.endsWith?.('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)) : '—'
export function fmtBytes(value) {
  if (value == null) return '—'
  const n = value > 1048576 ? 1048576 : value > 1024 ? 1024 : 1
  return `${fmtNum(value / n, 1)} ${n === 1048576 ? 'МБ' : n === 1024 ? 'КБ' : 'Б'}`
}
export function countText(n, forms) {
  const k = Math.abs(n) % 100
  return `${n} ${forms[k > 10 && k < 20 ? 2 : k % 10 === 1 ? 0 : k % 10 >= 2 && k % 10 <= 4 ? 1 : 2]}`
}
export function metricParts(name, k) {
  const m = /^(V)(oc)$|^(J)(sc)$|^(T)(80|90|95)$/.exec(name || '')
  const parts = m ? [{ text: m[1] || m[3] || m[5] }, { text: m[2] || m[4] || m[6], sub: true }] : [{ text: name || '—' }]
  if (k !== null && k !== undefined && k !== '') parts.push({ text: `@${k}` })
  return parts
}
