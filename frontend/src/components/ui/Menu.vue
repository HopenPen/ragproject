<!-- Назначение файла: выпадающее меню: кнопка-триггер и список действий; закрывается по Esc, клику вне меню и выбору. -->
<script setup>
import { onBeforeUnmount, ref } from 'vue'

const props = defineProps({ align: { type: String, default: 'end' }, width: { type: String, default: '240px' } })
const open = ref(false)
const root = ref(null)
function onDoc (e) { if (!root.value?.contains(e.target)) close() }
function onKey (e) { if (e.key === 'Escape') close() }
function toggle () {
  open.value = !open.value
  if (open.value) {
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
  }
}
function close () {
  open.value = false
  document.removeEventListener('mousedown', onDoc)
  document.removeEventListener('keydown', onKey)
}
onBeforeUnmount(close)
defineExpose({ close })
</script>

<template>
  <div ref="root" class="menu">
    <slot name="trigger" :toggle="toggle" :open="open" />
    <Transition name="menu">
      <div v-if="open" class="menu__list" :class="`menu__list--${props.align}`" :style="{ width: props.width }" role="menu" @click="close">
        <slot />
      </div>
    </Transition>
  </div>
</template>

<style>
.menu { position: relative; }
.menu__list { position: absolute; top: calc(100% + 6px); z-index: 40; padding: 6px; background: var(--u-bg); border: 1px solid var(--u-border); border-radius: 12px; box-shadow: var(--u-shadow); }
.menu__list--end { right: 0; }
.menu__list--start { left: 0; }
.menu__item { display: flex; align-items: center; gap: 8px; width: 100%; height: 30px; padding: 0 8px; border: 0; border-radius: 6px; background: none; text-align: left; font-size: 13px; line-height: 16px; color: var(--u-muted); text-decoration: none !important; white-space: nowrap; }
.menu__item:hover { background: var(--u-fill-2); color: var(--u-ink); }
.menu__item svg { width: 15px; height: 15px; flex: none; }
.menu__item.is-active { color: var(--u-ink); font-weight: 500; background: var(--u-fill); }
.menu__item[disabled] { opacity: .45; pointer-events: none; }
.menu__sep { height: 1px; margin: 6px 2px; background: var(--u-line); }
.menu__label { padding: 6px 8px 4px; font-size: 13px; line-height: 16px; color: var(--u-soft); }
.menu-enter-active, .menu-leave-active { transition: opacity 140ms var(--u-ease), transform 160ms var(--u-ease); }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
