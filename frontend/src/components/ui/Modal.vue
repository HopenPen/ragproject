<!-- Назначение файла: модальное окно: заголовок, содержимое, подвал с действиями; Esc и клик по фону закрывают,
     фокус переходит внутрь окна и возвращается обратно. На телефоне окно становится листом снизу. -->
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X } from '@lucide/vue'

const props = defineProps({ open: Boolean, title: String, width: { type: String, default: '520px' }, dismissible: { type: Boolean, default: true } })
const emit = defineEmits(['close'])
const box = ref(null)
let returnFocus = null

function onKey (e) {
  if (e.key === 'Escape' && props.dismissible) emit('close')
}
watch(() => props.open, async open => {
  if (open) {
    returnFocus = document.activeElement
    document.addEventListener('keydown', onKey)
    await nextTick()
    const first = box.value?.querySelector('[autofocus], input, select, textarea, button.btn--primary')
    ;(first || box.value)?.focus()
  } else {
    document.removeEventListener('keydown', onKey)
    returnFocus?.focus?.()
  }
}, { immediate: true })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal" @mousedown.self="dismissible && emit('close')">
        <section ref="box" class="modal__box" :style="{ '--w': width }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
          <header class="modal__head">
            <h2>{{ title }}</h2>
            <button v-if="dismissible" class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Закрыть" @click="emit('close')"><X /></button>
          </header>
          <div class="modal__body"><slot /></div>
          <footer v-if="$slots.footer" class="modal__foot"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.modal { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 24px; background: var(--scrim); }
.modal__box { width: min(var(--w), 100%); max-height: calc(100vh - 48px); display: flex; flex-direction: column; background: var(--u-bg); border: 1px solid var(--u-border); border-radius: 12px; box-shadow: var(--u-shadow); }
.modal__box:focus-visible { outline: none; }
.modal__head { display: flex; align-items: center; gap: 8px; height: 48px; flex: none; padding: 0 10px 0 16px; border-bottom: 1px solid var(--u-line); }
.modal__head h2 { flex: 1; font-size: 13px; line-height: 20px; font-weight: 500; }
.modal__body { padding: 16px; overflow: auto; }
.modal__foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--u-line); background: var(--u-fill); border-radius: 0 0 12px 12px; }
.modal-enter-active, .modal-leave-active { transition: opacity 180ms var(--u-ease); }
.modal-enter-active .modal__box, .modal-leave-active .modal__box { transition: transform 240ms var(--u-spring); }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .modal__box { transform: translateY(6px) scale(.98); }
@media (max-width: 719px) {
  .modal { place-items: end stretch; padding: 0; }
  .modal__box { width: 100%; max-height: 92vh; border-radius: 12px 12px 0 0; padding-bottom: env(safe-area-inset-bottom); }
  .modal-enter-from .modal__box { transform: translateY(32px); }
  .modal__foot { flex-direction: column-reverse; border-radius: 0; }
  .modal__foot .btn { width: 100%; }
}
</style>
