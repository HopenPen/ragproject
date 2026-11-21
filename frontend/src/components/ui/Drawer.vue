<!-- Назначение файла: боковая панель поверх страницы (история версий, задание, сравнение, паспорт).
     Справа на компьютере, лист во весь экран на телефоне. Esc и клик по фону закрывают. -->
<script setup>
import { onBeforeUnmount, watch } from 'vue'
import { X } from '@lucide/vue'

const props = defineProps({ open: Boolean, title: String, width: { type: String, default: '560px' } })
const emit = defineEmits(['close'])
function onKey (e) { if (e.key === 'Escape') emit('close') }
watch(() => props.open, open => {
  if (open) document.addEventListener('keydown', onKey)
  else document.removeEventListener('keydown', onKey)
}, { immediate: true })
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="drawer" @mousedown.self="emit('close')">
        <aside class="drawer__panel" :style="{ '--w': width }" role="dialog" aria-modal="true" :aria-label="title">
          <header class="drawer__head">
            <div class="drawer__title"><h2>{{ title }}</h2><slot name="subtitle" /></div>
            <slot name="actions" />
            <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Закрыть" @click="emit('close')"><X /></button>
          </header>
          <div class="drawer__body"><slot /></div>
          <footer v-if="$slots.footer" class="drawer__foot"><slot name="footer" /></footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.drawer { position: fixed; inset: 0; z-index: 50; background: var(--scrim); display: flex; justify-content: flex-end; padding: 8px; }
.drawer__panel { width: min(var(--w), 100%); height: 100%; display: flex; flex-direction: column; background: var(--u-bg); border: 1px solid var(--u-border); border-radius: 12px; box-shadow: var(--u-shadow); overflow: hidden; }
.drawer__head { display: flex; align-items: center; gap: 8px; min-height: 56px; padding: 8px 10px 8px 16px; border-bottom: 1px solid var(--u-line); background: var(--u-fill); }
.drawer__title { flex: 1; min-width: 0; }
.drawer__title h2 { font-size: 13px; line-height: 20px; font-weight: 500; }
.drawer__body { flex: 1; overflow: auto; padding: 16px; }
.drawer__foot { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 16px; border-top: 1px solid var(--u-line); background: var(--u-fill); }
.drawer-enter-active, .drawer-leave-active { transition: opacity 200ms var(--u-ease); }
.drawer-enter-active .drawer__panel, .drawer-leave-active .drawer__panel { transition: transform 260ms var(--u-spring); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer__panel, .drawer-leave-to .drawer__panel { transform: translateX(16px); }
@media (max-width: 719px) {
  .drawer { padding: 0; }
  .drawer__panel { width: 100%; border-radius: 0; border: 0; padding-bottom: env(safe-area-inset-bottom); }
  .drawer-enter-from .drawer__panel, .drawer-leave-to .drawer__panel { transform: translateY(24px); }
}
</style>
