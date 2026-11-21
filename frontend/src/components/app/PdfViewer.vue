<!-- Назначение файла: просмотр PDF с рамками источников. Страницы рисует pdf.js по мере прокрутки,
     рамки ставятся по bbox в PDF points (начало сверху слева) в процентах от размера страницы,
     поэтому не зависят от масштаба. Выбранная рамка зелёная с подписью значения, с замечанием охристая.
     Бумага подкрашена приглушённым бежевым (--paper) через multiply, текст остаётся чёрным. -->
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ZoomIn, ZoomOut, Maximize2, FileWarning } from '@lucide/vue'
import { loadPdf, pdfErrorText } from '../../lib/pdf.js'

const props = defineProps({
  documentId: String,
  boxes: { type: Array, default: () => [] },
  activeId: String,
  activeLabel: String,
  focus: { type: Object, default: null }
})
const emit = defineEmits(['select', 'loaded'])

const scroller = ref(null)
const doc = shallowRef(null)
const sizes = ref([])
const error = ref(null)
const loading = ref(true)
const zoom = ref(1)
const fitWidth = ref(0)
const current = ref(1)
const rendered = new Map()
let io = null
let ro = null

const scale = computed(() => (fitWidth.value || 600) / (sizes.value[0]?.w || 595) * zoom.value)
const pageStyle = s => ({ width: `${s.w * scale.value}px`, height: `${s.h * scale.value}px` })
const boxesByPage = computed(() => {
  const m = {}
  for (const b of props.boxes) (m[b.page] ||= []).push(b)
  return m
})
function boxStyle (b, s) {
  const [x0, y0, x1, y1] = b.bbox
  return { left: `${x0 / s.w * 100}%`, top: `${y0 / s.h * 100}%`, width: `${(x1 - x0) / s.w * 100}%`, height: `${(y1 - y0) / s.h * 100}%` }
}

async function open () {
  loading.value = true
  error.value = null
  rendered.clear()
  try {
    const pdf = await loadPdf(props.documentId)
    const list = []
    for (let i = 1; i <= pdf.numPages; i++) {
      const vp = (await pdf.getPage(i)).getViewport({ scale: 1 })
      list.push({ n: i, w: vp.width, h: vp.height })
    }
    doc.value = pdf
    sizes.value = list
    loading.value = false
    emit('loaded', { pages: list.length })
    await nextTick()
    observe()
    if (props.focus) scrollToFocus(props.focus, false)
  } catch (e) {
    error.value = pdfErrorText(e)
    loading.value = false
  }
}

async function renderPage (n) {
  const canvas = scroller.value?.querySelector(`[data-page="${n}"] canvas`)
  if (!canvas || !doc.value) return
  const key = `${n}@${scale.value.toFixed(3)}`
  if (rendered.get(n) === key) return
  rendered.set(n, key)
  const page = await doc.value.getPage(n)
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
  const vp = page.getViewport({ scale: scale.value * dpr })
  canvas.width = Math.floor(vp.width)
  canvas.height = Math.floor(vp.height)
  try {
    await page.render({ canvas, viewport: vp }).promise
  } catch { rendered.delete(n) }
}

function observe () {
  io?.disconnect()
  io = new IntersectionObserver(entries => {
    for (const e of entries) {
      const n = Number(e.target.dataset.page)
      if (e.isIntersecting) renderPage(n)
    }
    const visible = [...scroller.value.querySelectorAll('[data-page]')].filter(el => {
      const r = el.getBoundingClientRect(); const s = scroller.value.getBoundingClientRect()
      return r.bottom > s.top + 80 && r.top < s.bottom - 80
    })
    if (visible.length) current.value = Number(visible[0].dataset.page)
  }, { root: scroller.value, rootMargin: '400px 0px', threshold: [0, 0.25, 0.5] })
  scroller.value?.querySelectorAll('[data-page]').forEach(el => io.observe(el))
}
function onScroll () {
  const s = scroller.value?.getBoundingClientRect()
  if (!s) return
  for (const el of scroller.value.querySelectorAll('[data-page]')) {
    const r = el.getBoundingClientRect()
    if (r.bottom > s.top + s.height * 0.35) { current.value = Number(el.dataset.page); break }
  }
}

function scrollToFocus (f, smooth = true) {
  const pageEl = scroller.value?.querySelector(`[data-page="${f.page}"]`)
  if (!pageEl) return
  const s = sizes.value[f.page - 1]
  let y = pageEl.offsetTop - 16
  if (f.bbox && s) y = pageEl.offsetTop + f.bbox[1] * scale.value - scroller.value.clientHeight * 0.32
  scroller.value.scrollTo({ top: Math.max(0, y), behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' })
}

function measure () {
  const w = scroller.value?.clientWidth || 0
  fitWidth.value = Math.max(280, Math.min(w - 48, 980))
}
function setZoom (z) {
  const keep = current.value
  zoom.value = Math.min(2.6, Math.max(0.6, z))
  nextTick(() => { scrollToFocus({ page: keep }, false); scroller.value?.querySelectorAll('[data-page]').forEach(el => { const r = el.getBoundingClientRect(); const s = scroller.value.getBoundingClientRect(); if (r.bottom > s.top - 400 && r.top < s.bottom + 400) renderPage(Number(el.dataset.page)) }) })
}

watch(() => props.documentId, () => open())
watch(() => props.focus, f => { if (f && sizes.value.length) nextTick(() => scrollToFocus(f)) })
watch(scale, () => { rendered.clear(); nextTick(() => io && observe()) })

onMounted(() => {
  measure()
  ro = new ResizeObserver(() => measure())
  ro.observe(scroller.value)
  open()
})
onBeforeUnmount(() => { io?.disconnect(); ro?.disconnect() })
defineExpose({ scrollToFocus })
</script>

<template>
  <div class="pdfv">
    <div class="pdfv__bar">
      <span class="pdfv__page num" aria-live="polite">{{ sizes.length ? `Стр. ${current} из ${sizes.length}` : 'PDF' }}</span>
      <span v-if="activeLabel" class="pdfv__sel"><span class="pdfv__selbox" />{{ activeLabel }}</span>
      <span class="grow" />
      <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Уменьшить" :disabled="!sizes.length" @click="setZoom(zoom - 0.2)"><ZoomOut /></button>
      <span class="pdfv__zoom num">{{ Math.round(zoom * 100) }}%</span>
      <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Увеличить" :disabled="!sizes.length" @click="setZoom(zoom + 0.2)"><ZoomIn /></button>
      <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="По ширине" :disabled="!sizes.length" @click="setZoom(1)"><Maximize2 /></button>
    </div>
    <div ref="scroller" class="pdfv__scroll" @scroll.passive="onScroll">
      <div v-if="error" class="pdfv__error">
        <FileWarning />
        <p>{{ error }}</p>
      </div>
      <div v-else-if="loading" class="pdfv__pages"><div class="pdfv__sheet skeleton" :style="{ width: `${fitWidth}px`, height: `${fitWidth * 1.41}px` }" /></div>
      <div v-else class="pdfv__pages">
        <div v-for="s in sizes" :key="s.n" class="pdfv__sheet" :data-page="s.n" :style="pageStyle(s)">
          <canvas />
          <div class="pdfv__paper" />
          <button
            v-for="b in boxesByPage[s.n] || []" :key="b.id" type="button" class="pin"
            :class="[`pin--${b.tone || 'idle'}`, { 'is-active': b.id === activeId }]"
            :style="boxStyle(b, s)" :aria-label="b.label" :title="b.label"
            @click="emit('select', b.id)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.pdfv { display: flex; flex-direction: column; min-height: 0; height: 100%; background: var(--surface-sunk); }
.pdfv__bar { display: flex; align-items: center; gap: 4px; height: 44px; padding: 0 10px 0 16px; border-bottom: 1px solid var(--line); background: var(--surface); }
.pdfv__page, .pdfv__zoom { font-size: var(--fs-sm); color: var(--muted); }
.pdfv__zoom { min-width: 42px; text-align: center; }
.pdfv__sel { display: inline-flex; align-items: center; gap: 8px; margin-left: 14px; padding-left: 14px; border-left: 1px solid var(--line); font-size: var(--fs-sm); font-weight: 500; color: var(--ink); font-variant-numeric: tabular-nums; white-space: nowrap; }
.pdfv__selbox { width: 14px; height: 10px; border-radius: 2px; box-shadow: 0 0 0 2px #07854A; background: rgba(7, 133, 74, .12); }
.pdfv__scroll { flex: 1; overflow: auto; position: relative; overscroll-behavior: contain; }
.pdfv__pages { display: flex; flex-direction: column; align-items: center; gap: 18px; padding: 24px; min-width: min-content; }
.pdfv__sheet { position: relative; flex: none; background: #fff; box-shadow: var(--shadow-page); border-radius: 2px; }
.pdfv__sheet canvas { position: absolute; inset: 0; width: 100%; height: 100%; border-radius: 2px; }
.pdfv__paper { position: absolute; inset: 0; background: var(--paper); mix-blend-mode: multiply; pointer-events: none; border-radius: 2px; }
.pdfv__error { display: flex; flex-direction: column; align-items: center; gap: 12px; max-width: 420px; margin: 80px auto; padding: 0 24px; text-align: center; color: var(--muted); }
.pdfv__error svg { width: 28px; height: 28px; color: var(--danger); }

.pin { position: absolute; padding: 0; margin: 0; border: 0; background: transparent; border-radius: 3px; cursor: pointer; transform: scale(1.06); }
.pin--idle { box-shadow: inset 0 0 0 1px rgba(7, 133, 74, .0); }
.pin--idle:hover { box-shadow: 0 0 0 1.5px rgba(7, 133, 74, .55); background: rgba(7, 133, 74, .06); }
.pdfv__sheet:hover .pin--idle { box-shadow: 0 0 0 1px rgba(7, 133, 74, .28); }
.pin--warn { box-shadow: 0 0 0 1.5px rgba(201, 138, 46, .85); background: rgba(201, 138, 46, .08); }
.pin--error { box-shadow: 0 0 0 1.5px rgba(168, 38, 29, .8); background: rgba(168, 38, 29, .07); }
.pin.is-active { z-index: 2; box-shadow: 0 0 0 2.5px #07854A, 0 0 0 6px rgba(7, 133, 74, .18); background: rgba(7, 133, 74, .1); animation: pin-in .5s var(--ease); }
.pin.is-active.pin--warn { box-shadow: 0 0 0 2.5px #B26F0E, 0 0 0 6px rgba(201, 138, 46, .22); background: rgba(201, 138, 46, .12); }
@keyframes pin-in { from { box-shadow: 0 0 0 14px rgba(7, 133, 74, 0), 0 0 0 0 rgba(7, 133, 74, 0); } }
</style>
