<!-- Назначение файла: вход по почте и паролю (POST /auth/login). Регистрации нет, учётки выдаёт администратор.
     Справа страница статьи на бумаге: значение в таблице отмечено рамкой, линия ведёт к заметке на полях,
     как в окне статьи внутри продукта. Положение линии меряется по фактической вёрстке. -->
<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../stores/session.js'
import BrandMark from '../components/app/BrandMark.vue'
import { API_MODE } from '../api/http.js'

const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref(route.query.expired ? 'Сессия закончилась. Войдите снова.' : '')
const busy = ref(false)
const demo = API_MODE === 'mock'

async function submit () {
  if (!email.value.trim() || !password.value) { error.value = 'Введите почту и пароль.'; return }
  busy.value = true
  error.value = ''
  try {
    await login(email.value.trim(), password.value)
    router.replace(typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/corpora')
  } catch (e) {
    error.value = e.status === 429 ? 'Слишком много попыток входа. Подождите минуту.' : e.message
  } finally {
    busy.value = false
  }
}
// линия от отмеченной ячейки к заметке: координаты берутся из вёрстки и пересчитываются при изменении размера
const art = ref(null)
const cell = ref(null)
const note = ref(null)
const lead = ref(null)
let ro = null
function place () {
  if (!art.value || !cell.value || !note.value) return
  const a = art.value.getBoundingClientRect()
  const c = cell.value.getBoundingClientRect()
  const yc = c.top + c.height / 2 - a.top
  note.value.style.top = `${Math.round(yc - 22)}px`
  const n = note.value.getBoundingClientRect()
  const x = c.right - a.left + 3
  lead.value = { left: `${x}px`, top: `${Math.round(yc)}px`, width: `${Math.max(0, n.left - a.left - x)}px` }
}
onMounted(() => {
  nextTick(place)
  if (window.ResizeObserver && art.value) { ro = new ResizeObserver(place); ro.observe(art.value) }
  document.fonts?.ready.then(place)
})
onBeforeUnmount(() => ro?.disconnect())
function demoLogin (who) {
  email.value = `${who}@demo.local`
  password.value = 'demo'
  submit()
}
</script>

<template>
  <div class="login">
    <section class="login__form">
      <div class="login__brand"><BrandMark /><span>Science Extract</span></div>
      <h1>Вход</h1>
      <p class="login__lead">Учётные записи выдаёт администратор сервиса.</p>
      <form class="login__fields" novalidate @submit.prevent="submit">
        <label class="field">
          <span class="field__label">Почта<span class="field__req" aria-hidden="true">*</span></span>
          <input v-model="email" class="input" type="email" aria-required="true" autocomplete="username" inputmode="email" :aria-invalid="!!error">
        </label>
        <label class="field">
          <span class="field__label">Пароль<span class="field__req" aria-hidden="true">*</span></span>
          <input v-model="password" class="input" type="password" aria-required="true" autocomplete="current-password" :aria-invalid="!!error">
        </label>
        <p v-if="error" class="field__error" role="alert">{{ error }}</p>
        <button class="btn btn--primary btn--lg btn--block" type="submit" :disabled="busy">{{ busy ? 'Вход…' : 'Войти' }}</button>
      </form>
      <div v-if="demo" class="login__demo">
        <p>Демо-режим: синтетические статьи, модель не вызывается.</p>
        <div class="login__demo-row">
          <button class="btn btn--sm" type="button" :disabled="busy" @click="demoLogin('editor')">Войти редактором</button>
          <button class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="demoLogin('viewer')">Войти читателем</button>
        </div>
      </div>
    </section>

    <section class="login__art" aria-hidden="true">
      <div ref="art" class="lart">
        <article class="lart__page">
          <p class="lart__run"><span>Synthetic Journal of Photovoltaics 4 (2025)</span><span>3</span></p>
          <h2>3. Results and discussion</h2>
          <p>Table 1 summarizes the photovoltaic parameters. PEAI treatment raises the open-circuit voltage of the champion device from 1.06 V to 1.12 V and the fill factor from 77.5% to 81.0%.</p>
          <p class="lart__cap"><b>Table 1.</b> Photovoltaic parameters under AM1.5G illumination (100 mW/cm²), active area 0.09 cm².</p>
          <table class="lart__table">
            <thead><tr><th>Device</th><th>V<sub>oc</sub> (V)</th><th>J<sub>sc</sub> (mA/cm²)</th><th>FF (%)</th><th>PCE (%)</th></tr></thead>
            <tbody>
              <tr><td>D1 (control)</td><td>1.06</td><td>23.2</td><td>77.5</td><td>19.1</td></tr>
              <tr><td>D2 (PEAI, 5 nm)</td><td>1.12</td><td>23.6</td><td>81.0</td><td><span ref="cell" class="lart__mark">21.4</span></td></tr>
              <tr><td>D2, mean of 20</td><td>1.11 ± 0.01</td><td>23.4 ± 0.2</td><td>79.0 ± 1.2</td><td>20.3 ± 0.5</td></tr>
            </tbody>
          </table>
          <p>The champion D2 device shows a stabilized PCE of 20.9% after 300 s at the maximum power point.</p>
        </article>
        <span v-if="lead" class="lart__lead" :style="lead" />
        <aside ref="note" class="lart__note">
          <p class="lart__head"><b>PCE</b><span>R4</span></p>
          <p class="lart__val">21,4 %</p>
          <p class="lart__ctx">D2 (PEAI, 5 nm), лучший прибор</p>
          <p class="lart__where">Стр. 3, Table 1, уверенность 0,96</p>
        </aside>
      </div>
      <p class="login__caption">Каждое значение в базе ведёт к своему месту в статье: странице, таблице и строке.</p>
    </section>
  </div>
</template>

<style>
.login { min-height: 100vh; display: grid; grid-template-columns: minmax(360px, 440px) 1fr; }
.login__form { display: flex; flex-direction: column; justify-content: center; padding: 40px clamp(24px, 5vw, 56px); }
.login__brand { display: flex; align-items: center; gap: 10px; margin-bottom: 56px; font-weight: 600; letter-spacing: -0.01em; }
.login h1 { font-size: var(--t-32); line-height: 38px; font-weight: 600; letter-spacing: -0.025em; }
.login__lead { margin-top: 6px; color: var(--pencil); }
.login__fields { display: flex; flex-direction: column; gap: 16px; margin-top: 28px; }
.login__fields .btn { margin-top: 6px; }
.login__demo { margin-top: 36px; padding-top: 18px; box-shadow: inset 0 1px 0 var(--rule); color: var(--pencil); }
.login__demo-row { display: flex; gap: 6px; margin-top: 10px; }

/* страница статьи на полке: бумага, отмеченная ячейка, линия к заметке на полях */
.login__art { display: flex; flex-direction: column; justify-content: center; gap: 28px; padding: 48px clamp(32px, 5vw, 80px); background: var(--shelf); overflow: hidden; }
.lart { position: relative; width: min(100%, 860px); padding-right: 296px; }
.lart__page { padding: 36px 40px 40px; border-radius: 2px; background: var(--paper); color: #24231F; font-family: var(--serif); font-size: 15px; line-height: 22px; box-shadow: 0 1px 2px rgb(0 0 0 / .12), 0 22px 48px -24px rgb(0 0 0 / .4); }
.lart__page p + p, .lart__page table + p { margin-top: 10px; }
.lart__run { display: flex; justify-content: space-between; padding-bottom: 6px; margin-bottom: 22px; font-size: 11px; line-height: 14px; color: #6C6A62; box-shadow: inset 0 -0.5px 0 #6C6A62; }
.lart__page h2 { font-family: var(--serif); font-size: 16px; line-height: 22px; font-weight: 700; margin-bottom: 8px; }
.lart__cap { margin-top: 14px !important; font-size: 12.5px; line-height: 17px; }
.lart__table { width: 100%; margin-top: 8px; font-size: 13px; line-height: 18px; font-variant-numeric: tabular-nums; }
.lart__table th { font-weight: 700; text-align: right; padding: 5px 0 4px 10px; box-shadow: inset 0 1.2px 0 #24231F, inset 0 -0.8px 0 #24231F; }
.lart__table td { text-align: right; padding: 4px 0 3px 10px; }
.lart__table th:first-child, .lart__table td:first-child { text-align: left; padding-left: 0; }
.lart__table tbody tr:last-child td { box-shadow: inset 0 -1.2px 0 #24231F; }
.lart__mark { display: inline-block; padding: 0 4px; margin: 0 -5px 0 0; border-radius: 3px; box-shadow: 0 0 0 2px #07854A; background: rgb(7 133 74 / .12); animation: lart-frame 420ms var(--spring) 260ms both; }
.lart__lead { position: absolute; height: 2px; margin-top: -1px; background: #07854A; transform-origin: left center; animation: lart-lead 360ms var(--ease) 520ms both; }
.lart__note { position: absolute; right: 0; width: 256px; padding: 16px 18px 18px; border-radius: 10px; background: var(--float); color: var(--ink); box-shadow: var(--shadow); animation: lart-note 420ms var(--spring) 760ms both; }
.lart__head { display: flex; justify-content: space-between; font-weight: 600; }
.lart__head span { font-weight: 400; color: var(--pencil); }
.lart__val { margin-top: 2px; font-size: var(--t-32); line-height: 38px; font-weight: 600; letter-spacing: -0.025em; font-variant-numeric: tabular-nums; }
.lart__ctx { color: var(--pencil); }
.lart__where { margin-top: 12px; padding-top: 10px; box-shadow: inset 0 1px 0 var(--rule); font-size: 13px; line-height: 18px; color: var(--pencil); }
.login__caption { max-width: 46ch; color: var(--pencil); font-size: var(--t-17); line-height: 24px; }
@keyframes lart-frame { from { box-shadow: 0 0 0 6px rgb(7 133 74 / 0); background: transparent; } }
@keyframes lart-lead { from { transform: scaleX(0); } }
@keyframes lart-note { from { opacity: 0; transform: translateX(-8px); } }
@media (prefers-reduced-motion: reduce) { .lart__mark, .lart__lead, .lart__note { animation: none; } }
@media (max-width: 1240px) { .lart { padding-right: 0; } .lart__note { position: relative; top: auto !important; margin: -36px 16px 0 auto; } .lart__lead { display: none; } }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .login__art { display: none; }
  .login__form { justify-content: flex-start; padding-top: 40px; }
  .login__brand { margin-bottom: 40px; }
}
</style>
