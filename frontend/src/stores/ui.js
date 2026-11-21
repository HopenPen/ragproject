// Назначение файла: состояние оформления: тема (светлая, тёмная, как в системе) и узкий экран телефона.
import { reactive } from 'vue'

const KEY = 'se-theme'
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')
const narrow = window.matchMedia('(max-width: 719px)')

function readPref () {
  try { return localStorage.getItem(KEY) || 'system' } catch { return 'system' }
}

export const ui = reactive({
  themePref: readPref(),
  theme: 'light',
  mobile: narrow.matches
})

function apply () {
  ui.theme = ui.themePref === 'system' ? (systemDark.matches ? 'dark' : 'light') : ui.themePref
  document.documentElement.dataset.theme = ui.theme
  const meta = document.querySelector('meta[name="theme-color"]:not([media])') || document.head.appendChild(Object.assign(document.createElement('meta'), { name: 'theme-color' }))
  meta.content = ui.theme === 'dark' ? '#1C1C1B' : '#EAE6DE'
}

export function setTheme (pref) {
  ui.themePref = pref
  try { localStorage.setItem(KEY, pref) } catch { /* без сохранения между визитами */ }
  apply()
}
export function toggleTheme () {
  setTheme(ui.theme === 'dark' ? 'light' : 'dark')
}

systemDark.addEventListener('change', apply)
narrow.addEventListener('change', e => { ui.mobile = e.matches })
apply()
