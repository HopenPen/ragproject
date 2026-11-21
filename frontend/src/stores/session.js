// Назначение файла: сессия пользователя: вход, восстановление по refresh-токену вкладки, выход,
// заблаговременное обновление access-токена за минуту до истечения, права на правку корпуса.
import { reactive } from 'vue'
import { auth } from '../api/index.js'
import { setTokens, clearTokens, tokens, refreshSession, configureAuth } from '../api/http.js'

export const session = reactive({ user: null, ready: false, lost: false })

let timer = null
function schedule () {
  clearTimeout(timer)
  if (!tokens.expiresAt) return
  const wait = Math.max(5000, tokens.expiresAt - Date.now() - 60000)
  timer = setTimeout(() => { refreshSession().then(schedule).catch(() => {}) }, wait)
}

let navigateToLogin = () => {}
export function onSessionLost (fn) { navigateToLogin = fn }

configureAuth({
  authLost: () => {
    if (!session.user) return
    session.user = null
    session.lost = true
    navigateToLogin()
  },
  tokensChanged: () => schedule()
})

export async function restoreSession () {
  if (tokens.refresh) {
    try {
      await refreshSession()
      session.user = await auth.me()
    } catch {
      clearTokens()
    }
  }
  session.ready = true
}

export async function login (email, password) {
  const pair = await auth.login(email, password)
  setTokens(pair)
  session.user = await auth.me()
  session.lost = false
}

export async function logout ({ everywhere = false } = {}) {
  const rt = tokens.refresh
  try {
    if (everywhere) await auth.logoutAll()
    else await auth.logout(rt)
  } finally {
    clearTimeout(timer)
    clearTokens()
    session.user = null
  }
}

/** Может ли текущий пользователь менять корпус: редактор-владелец или администратор, корпус не в архиве. */
export function canEdit (corpus) {
  return corpus?.status !== 'archived' && canManage(corpus)
}

export function canManage (corpus) {
  const u = session.user
  if (!u || !corpus) return false
  return u.role === 'admin' || (u.role === 'editor' && corpus.owner_id === u.id)
}
