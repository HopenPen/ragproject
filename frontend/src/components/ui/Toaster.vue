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
.toaster { position: fixed; left: 50%; bottom: 20px; z-index: 80; display: flex; flex-direction: column; gap: 8px; width: min(420px, calc(100vw - 32px)); transform: translateX(-50%); }
.toast { display: flex; align-items: flex-start; gap: 10px; padding: 12px 8px 12px 16px; background: var(--ink); color: var(--desk); border-radius: 10px; box-shadow: var(--shadow); }
.toast__icon { width: 16px !important; height: 16px !important; margin-top: 2px; flex: none; opacity: .7; }
.toast--ok .toast__icon { color: #4FB678; opacity: 1; }
.toast--error .toast__icon { color: #FF806A; opacity: 1; }
.toast__text { flex: 1; min-width: 0; }
.toast__title { font-weight: 500; }
.toast__sub { font-size: 13px; line-height: 18px; opacity: .72; margin-top: 2px; }
.toast .btn--ghost { color: inherit; opacity: .7; }
.toast .btn--ghost:hover { opacity: 1; background: transparent; }
.toast-enter-active, .toast-leave-active { transition: opacity 180ms var(--ease), transform 220ms var(--spring); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(10px); }
@media (max-width: 719px) { .toaster { bottom: calc(72px + env(safe-area-inset-bottom)); } }
</style>
