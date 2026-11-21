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
.menu__list { position: absolute; top: calc(100% + 8px); z-index: 40; padding: 6px; background: var(--float); border-radius: 10px; box-shadow: var(--shadow); }
.menu__list--end { right: 0; }
.menu__list--start { left: 0; }
.menu__item { display: flex; align-items: center; gap: 10px; width: 100%; height: 34px; padding: 0 10px; border: 0; border-radius: 6px; background: none; text-align: left; color: var(--ink); white-space: nowrap; }
.menu__item:hover { background: var(--hover); }
.menu__item svg { width: 15px; height: 15px; color: var(--pencil); flex: none; }
.menu__item.is-active { font-weight: 600; }
.menu__item.is-active::after { content: ""; width: 6px; height: 10px; margin-left: auto; border: solid var(--ink); border-width: 0 1.5px 1.5px 0; transform: rotate(45deg) translateY(-2px); }
.menu__item[disabled] { opacity: .4; pointer-events: none; }
.menu__sep { height: 1px; margin: 6px 4px; background: var(--rule); }
.menu__label { padding: 8px 10px 4px; font-size: 13px; color: var(--pencil); }
.menu-enter-active, .menu-leave-active { transition: opacity 120ms var(--ease), transform 160ms var(--ease); }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
