<!-- Назначение файла: вход по почте и паролю (POST /auth/login). Регистрации нет, учётки выдаёт администратор.
     Справа фрагмент таблицы статьи с числом в рамке источника: так в сервисе выглядит каждое извлечённое значение. -->
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
const cropUrl = import.meta.env.BASE_URL + 'brand/source-crop.svg'

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
      <figure class="login__sheet">
        <img :src="cropUrl" alt="" width="1612" height="450">
        <span class="login__paper" />
        <svg class="login__annotation" viewBox="0 0 1612 450" aria-hidden="true">
          <rect x="1378" y="282" width="88" height="52" rx="5" fill="#07854A" fill-opacity=".1" stroke="#07854A" stroke-width="4" />
          <path d="M1422 334v28" stroke="#07854A" stroke-width="3" />
          <rect x="1260" y="362" width="284" height="56" rx="6" fill="#07854A" />
          <text x="1280" y="400" fill="white" font-size="30" font-weight="500" font-family="Geologica, sans-serif">PCE 21,4 %</text>
        </svg>
      </figure>
      <p class="login__caption">Каждое значение в базе ведёт к своему месту в статье: странице, таблице и строке.</p>
    </section>
  </div>
</template>

<style>
.login { min-height: 100vh; display: grid; grid-template-columns: minmax(360px, 460px) 1fr; }
.login__form { display: flex; flex-direction: column; justify-content: center; padding: var(--s-10) clamp(24px, 5vw, 64px); background: var(--surface); border-right: 1px solid var(--line); }
.login__brand { display: flex; align-items: center; gap: 10px; margin-bottom: 56px; font-weight: 600; }
.login h1 { font-size: var(--fs-2xl); margin-bottom: 6px; }
.login__fields { margin-top: var(--s-6); gap: var(--s-4); }
.login__fields .btn { margin-top: var(--s-2); }
.login__demo { margin-top: var(--s-8); padding-top: var(--s-5); border-top: 1px solid var(--line); font-size: var(--fs-sm); color: var(--muted); }
.login__demo p { margin-bottom: 10px; }
.login__demo b { color: var(--ink); font-weight: 600; }
.login__art { display: flex; flex-direction: column; justify-content: center; gap: var(--s-5); padding: var(--s-10) clamp(32px, 6vw, 96px); overflow: hidden; }
.login__sheet { position: relative; margin: 0; width: min(100%, 860px); background: #fff; box-shadow: var(--shadow-page); border-radius: 3px; }
.login__sheet img { width: 100%; height: auto; border-radius: 3px; }
.login__paper { position: absolute; inset: 0; background: var(--paper); mix-blend-mode: multiply; border-radius: 3px; }
.login__annotation { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.login__caption { max-width: 46ch; color: var(--muted); font-size: var(--fs-lg); line-height: 1.5; }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .login__art { display: none; }
  .login__form { border-right: 0; justify-content: flex-start; padding-top: 48px; }
  .login__brand { margin-bottom: 40px; }
}
</style>
