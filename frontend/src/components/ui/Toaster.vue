<!-- Назначение файла: стопка уведомлений в углу экрана; у ошибок номер запроса для поддержки. -->
<script setup>
import { CircleCheck, CircleAlert, Info, X } from '@lucide/vue'
import { toasts, dismiss } from '../../stores/toasts.js'
const ICON = { ok: CircleCheck, error: CircleAlert, info: Info }
</script>

<template>
  <div class="toaster" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast--${t.tone}`" role="status">
        <component :is="ICON[t.tone] || Info" class="toast__icon" />
        <div class="toast__text">
          <p class="toast__title">{{ t.title }}</p>
          <p v-if="t.text" class="toast__sub">{{ t.text }}</p>
          <p v-if="t.requestId" class="toast__sub">Номер запроса <span class="mono">{{ t.requestId }}</span></p>
        </div>
        <button v-if="t.action" class="btn btn--sm" type="button" @click="t.action.run(); dismiss(t.id)">{{ t.action.label }}</button>
        <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Скрыть" @click="dismiss(t.id)"><X /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style>
.toaster { position: fixed; right: var(--s-5); bottom: var(--s-5); z-index: 80; display: flex; flex-direction: column; gap: var(--s-2); width: min(400px, calc(100vw - 32px)); }
.toast { display: flex; align-items: flex-start; gap: var(--s-3); padding: 12px 10px 12px 14px; background: var(--ink); color: var(--bg); border-radius: var(--r-lg); box-shadow: var(--shadow-overlay); }
.toast .btn--ghost { color: inherit; opacity: .7; }
.toast .btn--ghost:hover { background: rgba(255, 255, 255, .1); opacity: 1; }
[data-theme="dark"] .toast .btn--ghost:hover { background: rgba(0, 0, 0, .08); }
.toast__icon { width: 18px; height: 18px; margin-top: 1px; flex: none; }
.toast--ok .toast__icon { color: #5CCB95; }
[data-theme="dark"] .toast--ok .toast__icon { color: var(--accent); }
.toast--error .toast__icon { color: #F2897F; }
[data-theme="dark"] .toast--error .toast__icon { color: var(--danger-line); }
.toast__text { flex: 1; min-width: 0; }
.toast__title { font-weight: 500; }
.toast__sub { font-size: var(--fs-sm); opacity: .75; margin-top: 2px; }
.toast-enter-active, .toast-leave-active { transition: opacity .2s var(--ease), transform .2s var(--ease); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
@media (max-width: 719px) { .toaster { right: 16px; bottom: calc(var(--tabbar-h) + 12px); } }
</style>
