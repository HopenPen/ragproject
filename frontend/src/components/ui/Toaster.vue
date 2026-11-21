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
.toaster { position: fixed; right: 16px; bottom: 16px; z-index: 80; display: flex; flex-direction: column; gap: 8px; width: min(380px, calc(100vw - 32px)); }
.toast { display: flex; align-items: flex-start; gap: 10px; padding: 10px 8px 10px 14px; background: var(--u-bg); color: var(--u-ink); border: 1px solid var(--u-border); border-radius: 12px; box-shadow: var(--u-shadow); }
.toast__icon { width: 16px; height: 16px; margin-top: 2px; flex: none; color: var(--u-muted); }
.toast--ok .toast__icon { color: var(--u-accent-text); }
.toast--error .toast__icon { color: var(--danger); }
.toast__text { flex: 1; min-width: 0; }
.toast__title { font-weight: 500; }
.toast__sub { font-size: 12px; line-height: 16px; color: var(--u-muted); margin-top: 2px; }
.toast-enter-active, .toast-leave-active { transition: opacity 200ms var(--u-ease), transform 240ms var(--u-spring); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
@media (max-width: 719px) { .toaster { right: 16px; bottom: calc(var(--tabbar-h) + 12px); } }
</style>
