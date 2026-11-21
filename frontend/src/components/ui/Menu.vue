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
.menu__list { position: absolute; top: calc(100% + 6px); z-index: 40; padding: 6px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--shadow-overlay); }
.menu__list--end { right: 0; }
.menu__list--start { left: 0; }
.menu__item { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 36px; padding: 6px 10px; border: 0; border-radius: var(--r-sm); background: none; text-align: left; font-size: var(--fs-md); color: var(--ink); cursor: pointer; text-decoration: none; }
.menu__item:hover { background: var(--surface-hover); text-decoration: none; }
.menu__item svg { width: 16px; height: 16px; color: var(--muted); flex: none; }
.menu__item.is-active { color: var(--accent-text); font-weight: 500; }
.menu__item[disabled] { opacity: .5; pointer-events: none; }
.menu__sep { height: 1px; margin: 6px 4px; background: var(--line); }
.menu__label { padding: 6px 10px 4px; font-size: var(--fs-xs); color: var(--muted); }
.menu-enter-active, .menu-leave-active { transition: opacity .12s var(--ease), transform .12s var(--ease); }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
