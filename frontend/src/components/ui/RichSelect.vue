<!-- Назначение файла: выпадающий список, у которого вариант пишется в два начертания: короткое имя жирным,
     через дефис пояснение обычным (dev - настройка и проверка на размеченных статьях). Обычный select так
     не умеет. Клавиатура как у списка: стрелки, Enter или пробел, Esc, Home и End. Список выносится в body
     и ставится по кнопке, чтобы его не обрезало окно диалога. -->
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: null },
  options: { type: Array, required: true },
  labelledby: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])
const uid = useId()
const open = ref(false)
const active = ref(0)
const root = ref(null)
const btn = ref(null)
const list = ref(null)
const pos = ref({})
const current = computed(() => props.options.find(o => o.value === props.modelValue) || props.options[0])

function onDoc (e) { if (!root.value?.contains(e.target) && !list.value?.contains(e.target)) close() }
function onMove () { close() }
// список под кнопкой, а если снизу мало места, над ней
function place () {
  const r = btn.value.getBoundingClientRect()
  const h = Math.min(280, props.options.length * 40 + 12)
  const below = window.innerHeight - r.bottom
  const up = below < h + 12 && r.top > below
  pos.value = { left: `${r.left}px`, width: `${r.width}px`, top: up ? 'auto' : `${r.bottom + 6}px`, bottom: up ? `${window.innerHeight - r.top + 6}px` : 'auto' }
}
function show () {
  if (open.value) return
  place()
  open.value = true
  active.value = Math.max(0, props.options.findIndex(o => o.value === props.modelValue))
  document.addEventListener('mousedown', onDoc)
  window.addEventListener('resize', onMove)
  window.addEventListener('scroll', onMove, true)
}
function close (focus = false) {
  open.value = false
  document.removeEventListener('mousedown', onDoc)
  window.removeEventListener('resize', onMove)
  window.removeEventListener('scroll', onMove, true)
  if (focus) nextTick(() => btn.value?.focus())
}
function pick (o) {
  emit('update:modelValue', o.value)
  close(true)
}
function onKey (e) {
  const n = props.options.length
  if (['ArrowDown', 'ArrowUp'].includes(e.key)) {
    e.preventDefault()
    if (!open.value) { show(); return }
    active.value = (active.value + (e.key === 'ArrowDown' ? 1 : -1) + n) % n
  } else if (e.key === 'Home' && open.value) { e.preventDefault(); active.value = 0 }
  else if (e.key === 'End' && open.value) { e.preventDefault(); active.value = n - 1 }
  else if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    if (open.value) pick(props.options[active.value]); else show()
  } else if (e.key === 'Escape' && open.value) { e.preventDefault(); e.stopPropagation(); close(true) }
  else if (e.key === 'Tab') close()
}
onBeforeUnmount(() => close())
</script>

<template>
  <div ref="root" class="rsel" :class="{ 'is-open': open }">
    <button
      ref="btn" type="button" class="select rsel__btn" role="combobox" aria-haspopup="listbox"
      :aria-expanded="open" :aria-controls="`${uid}-list`" :aria-labelledby="labelledby || null"
      :aria-activedescendant="open ? `${uid}-${active}` : null"
      @click="open ? close() : show()" @keydown="onKey"
    >
      <span class="rsel__text"><b>{{ current?.title }}</b><template v-if="current?.text"> - {{ current.text }}</template></span>
    </button>
    <Teleport to="body">
    <ul v-show="open" :id="`${uid}-list`" ref="list" class="rsel__list" :style="pos" role="listbox" :aria-labelledby="labelledby || null">
      <li
        v-for="(o, i) in options" :id="`${uid}-${i}`" :key="String(o.value)" role="option"
        class="rsel__opt" :class="{ 'is-active': i === active }" :aria-selected="o.value === modelValue"
        @mousedown.prevent="pick(o)" @mousemove="active = i"
      >
        <b>{{ o.title }}</b><template v-if="o.text"> - {{ o.text }}</template>
      </li>
    </ul>
    </Teleport>
  </div>
</template>

<style>
.rsel { position: relative; }
.rsel__btn { display: flex; align-items: center; text-align: left; cursor: pointer; }
.rsel__text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; }
.rsel__text b, .rsel__opt b { font-weight: 600; }
.rsel.is-open .rsel__btn { border-color: var(--ink); }
.rsel__list { position: fixed; z-index: 90; max-height: 280px; overflow: auto; padding: 6px; background: var(--float); border-radius: 10px; box-shadow: var(--shadow); }
.rsel__opt { padding: 8px 10px; border-radius: 6px; line-height: 20px; color: var(--ink); cursor: pointer; }
.rsel__opt.is-active { background: var(--hover); }
.rsel__opt[aria-selected="true"] { box-shadow: inset 2px 0 0 #07854A; }
</style>
