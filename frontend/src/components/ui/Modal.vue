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
.modal__box { width: min(var(--w), 100%); max-height: calc(100vh - 48px); display: flex; flex-direction: column; background: var(--float); border-radius: 10px; box-shadow: var(--shadow); }
.modal__box:focus-visible { outline: none; }
.modal__head { display: flex; align-items: center; gap: 8px; flex: none; padding: 18px 14px 6px 22px; }
.modal__head h2 { flex: 1; font-size: var(--t-17); line-height: 24px; font-weight: 600; letter-spacing: -0.01em; }
.modal__body { padding: 12px 22px 20px; overflow: auto; }
.modal__foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 22px 18px; box-shadow: inset 0 1px 0 var(--rule); }
.modal-enter-active, .modal-leave-active { transition: opacity 160ms var(--ease); }
.modal-enter-active .modal__box, .modal-leave-active .modal__box { transition: transform 220ms var(--spring); }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .modal__box { transform: translateY(8px); }
@media (max-width: 719px) {
  .modal { place-items: end stretch; padding: 0; }
  .modal__box { width: 100%; max-height: 92vh; border-radius: 12px 12px 0 0; padding-bottom: env(safe-area-inset-bottom); }
  .modal-enter-from .modal__box { transform: translateY(32px); }
  .modal__foot { flex-direction: column-reverse; }
  .modal__foot .btn { width: 100%; }
}
</style>
