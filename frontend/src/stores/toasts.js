// Назначение файла: короткие уведомления о результате действия и ошибки с request_id для поддержки.
import { reactive } from 'vue'

export const toasts = reactive([])
let seq = 0

export function toast (tone, title, opts = {}) {
  const id = ++seq
  toasts.push({ id, tone, title, text: opts.text || null, requestId: opts.requestId || null, action: opts.action || null })
  setTimeout(() => dismiss(id), opts.timeout ?? (tone === 'error' ? 9000 : 4500))
  return id
}
export function dismiss (id) {
  const i = toasts.findIndex(t => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
export const notify = {
  ok: (title, opts) => toast('ok', title, opts),
  info: (title, opts) => toast('info', title, opts),
  error: (err, fallback = 'Не получилось') => toast('error', err?.message || fallback, { requestId: err?.requestId })
}
