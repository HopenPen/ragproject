<!-- Назначение файла: вход по почте и паролю (POST /auth/login). Регистрации нет, учётки выдаёт администратор.
     Справа страница статьи из UI-кита (как на лендинге): отмеченное значение и заметка с его источником. -->
<script setup>
import { ref } from 'vue'
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
      <p class="muted">Учётные записи выдаёт администратор сервиса.</p>
      <form class="stack login__fields" novalidate @submit.prevent="submit">
        <label class="field">
          <span class="field__label">Почта</span>
          <input v-model="email" class="input" type="email" autocomplete="username" inputmode="email" :aria-invalid="!!error">
        </label>
        <label class="field">
          <span class="field__label">Пароль</span>
          <input v-model="password" class="input" type="password" autocomplete="current-password" :aria-invalid="!!error">
        </label>
        <p v-if="error" class="field__error" role="alert">{{ error }}</p>
        <button class="btn btn--primary btn--lg btn--block" type="submit" :disabled="busy">{{ busy ? 'Вход…' : 'Войти' }}</button>
      </form>
      <div v-if="demo" class="login__demo">
        <p><b>Демо-режим.</b> Синтетические статьи, модель не вызывается.</p>
        <div class="row">
          <button class="btn btn--sm" type="button" :disabled="busy" @click="demoLogin('editor')">Войти редактором</button>
          <button class="btn btn--sm" type="button" :disabled="busy" @click="demoLogin('viewer')">Войти читателем</button>
        </div>
      </div>
    </section>
    <section class="login__art" aria-hidden="true">
      <div class="ui-doc login__doc">
        <article class="ui-doc__page">
          <div class="ui-doc__label">P103, стр. 5 из 14</div>
          <div class="ui-doc__title">3.2 Photovoltaic performance</div>
          <div class="ui-doc__text">The champion device reached a PCE of <mark class="ui-doc__mark is-on">21.4%</mark> under AM1.5G illumination at 100&nbsp;mW&nbsp;cm⁻², with V<sub>oc</sub> of 1.12&nbsp;V, J<sub>sc</sub> of 23.9&nbsp;mA&nbsp;cm⁻² and FF of 80.1% in the reverse scan.</div>
          <div class="ui-doc__text">Across 24 devices of the same batch the mean PCE was <mark class="ui-doc__mark is-seen">20.3&nbsp;±&nbsp;0.6%</mark>.</div>
          <div class="ui-doc__text">The forward scan gave <mark class="ui-doc__mark is-seen">19.8%</mark>, indicating weak hysteresis.</div>
          <div class="ui-doc__text">The active area of 0.09&nbsp;cm² was defined by a metal aperture mask.</div>
        </article>
        <aside class="ui-doc__note ui-panel is-on">
          <div class="ui-doc__kind"><span class="ui-doc__dot" />Источник</div>
          <div class="ui-doc__msg">PCE 21,4 %, прибор D2, лучший, обратный ход</div>
          <div class="ui-doc__where">Стр. 5, раздел 3.2, уверенность 0,94</div>
        </aside>
      </div>
      <p class="login__caption">Каждое значение в базе ведёт к своему месту в статье: странице, таблице и строке.</p>
    </section>
  </div>
</template>

<style>
.login { min-height: 100vh; display: grid; grid-template-columns: minmax(360px, 440px) 1fr; }
.login__form { display: flex; flex-direction: column; justify-content: center; padding: 40px clamp(24px, 5vw, 56px); box-shadow: inset -1px 0 0 var(--u-line); }
.login__brand { display: flex; align-items: center; gap: 10px; margin-bottom: 48px; font-weight: 500; }
.login h1 { font-size: 24px; line-height: 32px; font-weight: 500; letter-spacing: -0.02em; margin-bottom: 4px; }
.login__fields { margin-top: 24px; gap: 14px; }
.login__fields .btn { margin-top: 6px; }
.login__demo { margin-top: 32px; padding-top: 18px; box-shadow: inset 0 1px 0 var(--u-line); color: var(--u-muted); }
.login__demo p { margin-bottom: 10px; }
.login__demo b { color: var(--u-ink); font-weight: 500; }
.login__art { display: flex; flex-direction: column; justify-content: center; gap: 24px; padding: 40px clamp(32px, 6vw, 96px); background: var(--fx-surface); overflow: hidden; }
/* страница статьи на бумаге, заметка с источником в поле справа, как в окне продукта на лендинге */
.login__doc { width: min(100%, 680px); padding-right: 216px; }
.login__doc .ui-doc__page { border-radius: 10px; border: 1px solid rgb(0 0 0 / .08); background: var(--paper); color: #24231F; box-shadow: 0 1px 2px rgb(0 0 0 / .10), 0 18px 40px -18px rgb(0 0 0 / .35); }
.login__doc .ui-doc__label { color: #6C6A62; }
.login__doc .ui-doc__text { color: #34332D; }
.login__doc .ui-doc__mark { --u-tint-2: rgb(7 133 74 / .2); }
.login__doc .ui-doc__mark.is-on { box-shadow: inset 0 -1.5px 0 #07854A; }
.login__doc .ui-doc__mark.is-seen { box-shadow: inset 0 -1px 0 rgb(36 35 31 / .45); }
.login__doc .ui-doc__note { top: 92px; width: 200px; }
.login__caption { max-width: 46ch; color: var(--u-text-2); font-size: 15px; line-height: 22px; }
@media (max-width: 1180px) { .login__doc { padding-right: 0; } .login__doc .ui-doc__note { position: relative; top: 0; margin: -24px 0 0 auto; } }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .login__art { display: none; }
  .login__form { box-shadow: none; justify-content: flex-start; padding-top: 48px; }
}
</style>
