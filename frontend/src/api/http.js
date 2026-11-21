// Назначение файла: HTTP-клиент интерфейса для API из раздела 8 ТЗ.
// Реализовано: access-токен только в памяти, refresh-токен в sessionStorage вкладки;
// single-flight обновление пары при 401 (параллельные запросы ждут одно обновление, иначе ротация
// с reuse detection отозвала бы всю семью токенов); разбор ошибок {error:{code,message,details,request_id}};
// ETag и If-Match для правок; Idempotency-Key для заданий; загрузка файла с прогрессом; скачивание blob.
// В режиме mock тот же код ходит в демо-сервер внутри браузера (src/api/mock/server.js) вместо fetch.

export const API_MODE = 'live'
export const API_BASE = (import.meta.env?.VITE_API_BASE || '/api/v1').replace(/\/$/, '')

const REFRESH_KEY = 'se-refresh'

export const tokens = {
  access: null,
  refresh: readRefresh(),
  expiresAt: 0
}
let onAuthLost = () => {}
let onTokens = () => {}
export function configureAuth ({ authLost, tokensChanged }) {
  if (authLost) onAuthLost = authLost
  if (tokensChanged) onTokens = tokensChanged
}

function readRefresh () {
  try { return sessionStorage.getItem(REFRESH_KEY) } catch { return null }
}
function writeRefresh (value) {
  try {
    if (value) sessionStorage.setItem(REFRESH_KEY, value)
    else sessionStorage.removeItem(REFRESH_KEY)
  } catch { /* приватный режим: токен живёт только в памяти */ }
}

export function setTokens (pair) {
  tokens.access = pair?.access_token ?? null
  tokens.refresh = pair?.refresh_token ?? null
  tokens.expiresAt = pair?.expires_in ? Date.now() + pair.expires_in * 1000 : 0
  writeRefresh(tokens.refresh)
  onTokens(tokens)
}
export function clearTokens () {
  setTokens(null)
}

export class ApiError extends Error {
  constructor ({ status, code, message, details, requestId }) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

const STATUS_TEXT = {
  0: 'Нет связи с сервером. Проверьте сеть и повторите.',
  400: 'Запрос не принят сервером.',
  401: 'Нужно войти заново.',
  403: 'Недостаточно прав для этого действия.',
  404: 'Не найдено или нет доступа.',
  409: 'Конфликт с текущими данными.',
  410: 'Файл больше не хранится.',
  412: 'Данные уже изменились. Обновите и повторите правку.',
  413: 'Файл слишком большой.',
  415: 'Неподдерживаемый тип файла.',
  422: 'Проверьте заполнение полей.',
  428: 'Не передана версия для правки.',
  429: 'Слишком много попыток. Повторите чуть позже.',
  503: 'Сервис временно недоступен.'
}

let transportPromise = null
async function transport () {
  if (!transportPromise) {
    transportPromise = Promise.resolve((url, init) => fetch(url, init))
  }
  return transportPromise
}

function buildUrl (path, query) {
  const url = new URL(API_BASE + path, window.location.origin)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)) continue
      if (Array.isArray(v)) v.forEach(x => url.searchParams.append(k, x))
      else url.searchParams.set(k, v)
    }
  }
  return url.href
}

async function toError (res) {
  let body = null
  try { body = await res.json() } catch { /* пустое тело у шлюза */ }
  const err = body?.error || {}
  return new ApiError({
    status: res.status,
    code: err.code || `http_${res.status}`,
    message: err.message || STATUS_TEXT[res.status] || `Ошибка ${res.status}`,
    details: err.details || null,
    requestId: err.request_id || res.headers.get('x-request-id') || null
  })
}

let refreshing = null
export function refreshSession () {
  if (!refreshing) {
    refreshing = (async () => {
      if (!tokens.refresh) throw new ApiError({ status: 401, code: 'no_refresh', message: STATUS_TEXT[401] })
      const res = await send('POST', '/auth/refresh', { body: { refresh_token: tokens.refresh }, auth: false })
      setTokens(res.data)
      return res.data
    })().finally(() => { refreshing = null })
  }
  return refreshing
}

async function send (method, path, opts = {}) {
  const { query, body, headers = {}, auth = true, ifMatch, idempotencyKey, as = 'json', signal } = opts
  const doFetch = await transport()
  const h = { Accept: 'application/json', ...headers }
  let payload
  if (body instanceof FormData || body instanceof Blob) payload = body
  else if (body !== undefined) {
    payload = JSON.stringify(body)
    h['Content-Type'] = 'application/json'
  }
  if (auth && tokens.access) h.Authorization = `Bearer ${tokens.access}`
  if (ifMatch) h['If-Match'] = ifMatch
  if (idempotencyKey) h['Idempotency-Key'] = idempotencyKey

  let res
  try {
    res = await doFetch(buildUrl(path, query), { method, headers: h, body: payload, signal })
  } catch (e) {
    if (e?.name === 'AbortError') throw e
    throw new ApiError({ status: 0, code: 'network', message: STATUS_TEXT[0] })
  }

  if (res.status === 401 && auth && !opts._retried && tokens.refresh) {
    try {
      await refreshSession()
    } catch {
      clearTokens()
      onAuthLost()
      throw await toError(res)
    }
    return send(method, path, { ...opts, _retried: true })
  }
  if (!res.ok) {
    const err = await toError(res)
    if (res.status === 401 && auth) {
      clearTokens()
      onAuthLost()
    }
    throw err
  }

  const etag = res.headers.get('etag')
  let data = null
  if (res.status !== 204) {
    if (as === 'blob') data = await res.blob()
    else if (as === 'arrayBuffer') data = await res.arrayBuffer()
    else {
      const text = await res.text()
      data = text ? JSON.parse(text) : null
    }
  }
  return { data, etag, status: res.status, headers: res.headers }
}

export const http = {
  get: (path, opts) => send('GET', path, opts),
  post: (path, body, opts) => send('POST', path, { ...opts, body }),
  patch: (path, body, opts) => send('PATCH', path, { ...opts, body }),
  put: (path, body, opts) => send('PUT', path, { ...opts, body }),
  del: (path, opts) => send('DELETE', path, opts)
}

/** Загрузка multipart с прогрессом. fetch не сообщает прогресс отправки, поэтому в live-режиме XHR. */
export async function upload (path, formData, { onProgress, idempotencyKey } = {}) {
  const attempt = () => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', buildUrl(path))
    xhr.setRequestHeader('Accept', 'application/json')
    if (tokens.access) xhr.setRequestHeader('Authorization', `Bearer ${tokens.access}`)
    if (idempotencyKey) xhr.setRequestHeader('Idempotency-Key', idempotencyKey)
    xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total) }
    xhr.onerror = () => reject(new ApiError({ status: 0, code: 'network', message: STATUS_TEXT[0] }))
    xhr.onload = () => {
      const headers = new Headers()
      xhr.getAllResponseHeaders().trim().split(/[\r\n]+/).forEach(line => {
        const i = line.indexOf(':')
        if (i > 0) headers.set(line.slice(0, i).trim(), line.slice(i + 1).trim())
      })
      resolve(new Response(xhr.status === 204 ? null : xhr.responseText, { status: xhr.status, headers }))
    }
    xhr.send(formData)
  })
  let res = await attempt()
  if (res.status === 401 && tokens.refresh) {
    await refreshSession()
    res = await attempt()
  }
  if (!res.ok) throw await toError(res)
  return { data: await res.json(), status: res.status }
}

/** Скачать файл ответа и отдать браузеру под именем из Content-Disposition. */
export async function download (path, fallbackName) {
  const res = await send('GET', path, { as: 'blob' })
  const cd = res.headers.get('content-disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(cd)
  const name = m ? decodeURIComponent(m[1] || m[2]) : fallbackName
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  return name
}

export function newIdempotencyKey () {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}
