<!-- Назначение файла: страницы PDF на столе. pdf.js рисует страницы по мере прокрутки, рамки источников
     ставятся по bbox в PDF points (начало сверху слева) в процентах от страницы и не зависят от масштаба.
     Справа от страниц поля: заметка к выбранному числу стоит на его высоте и связана с рамкой линией.
     Выбор числа это единственное движение экрана: страница прокручивается, рамка проявляется, линия
     дотягивается до заметки. Бумага подкрашена приглушённым бежевым через multiply, текст остаётся чёрным.
     Поиск внутри статьи (Ctrl+F или ⌘F): страницы нарисованы на canvas, поэтому браузерный поиск их не видит.
     Текст берётся из текстового слоя pdf.js, совпадения отмечаются графитом поверх бумаги, текущее обведено. -->
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ZoomIn, ZoomOut, FileWarning, Search, ChevronUp, ChevronDown, X } from '@lucide/vue'
import { loadPdf, pdfErrorText } from '../../lib/pdf.js'

const props = defineProps({
  documentId: String,
  boxes: { type: Array, default: () => [] },
  activeId: String,
  activeLabel: String,
  focus: { type: Object, default: null },
  margin: Boolean
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
// поля справа: ширина заметки и зазор до страницы
const NOTE_W = 300
const GAP = 40
const PAGE_GAP = 24
const activeBox = computed(() => props.boxes.find(b => b.id === props.activeId && b.bbox) || null)
function pageTop (n) {
  let y = 0
  for (const p of sizes.value) { if (p.n >= n) break; y += p.h * scale.value + PAGE_GAP }
  return y
}
const noteStyle = computed(() => {
  const b = activeBox.value
  if (!b) return {}
  const yc = (b.bbox[1] + b.bbox[3]) / 2 * scale.value
  return { top: `${Math.max(0, pageTop(b.page) + yc - 22)}px` }
})
const leadStyle = computed(() => {
  const b = activeBox.value
  const s = b && sizes.value[b.page - 1]
  if (!s) return {}
  const x = b.bbox[2] * scale.value + 3
  return { left: `${x}px`, top: `${(b.bbox[1] + b.bbox[3]) / 2 * scale.value}px`, width: `${s.w * scale.value - x + GAP}px` }
})
const pageStyle = s => ({ width: `${s.w * scale.value}px`, height: `${s.h * scale.value}px` })
const boxesByPage = computed(() => {
  const m = {}
  for (const b of props.boxes) (m[b.page] ||= []).push(b)
  return m
})
// прямоугольник в points страницы (начало сверху слева) в процентах, как у рамок источников
function rectStyle (r, s) {
  return { left: `${r[0] / s.w * 100}%`, top: `${r[1] / s.h * 100}%`, width: `${(r[2] - r[0]) / s.w * 100}%`, height: `${(r[3] - r[1]) / s.h * 100}%` }
}
function boxStyle (b, s) {
  const [x0, y0, x1, y1] = b.bbox
  return { left: `${x0 / s.w * 100}%`, top: `${y0 / s.h * 100}%`, width: `${(x1 - x0) / s.w * 100}%`, height: `${(y1 - y0) / s.h * 100}%` }
}

async function open () {
  loading.value = true
  error.value = null
  rendered.clear()
  texts.clear()
  hits.value = []
  hitIndex.value = -1
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
    if (findOpen.value && query.value.trim()) runSearch()
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
  if (f.bbox && s) y = pageEl.offsetTop + f.bbox[1] * scale.value - scroller.value.clientHeight * 0.3
  scroller.value.scrollTo({ top: Math.max(0, y), behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' })
}

// ---------------------------------------------------------------- поиск по тексту статьи
const findOpen = ref(false)
const query = ref('')
const findInput = ref(null)
const searching = ref(false)
const hits = shallowRef([])
const hitIndex = ref(-1)
const texts = new Map()
let searchSeq = 0
let searchTimer = null
const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
const findKey = isMac ? '⌘F' : 'Ctrl+F'

// сравнение без учёта регистра, лигатур (ﬁ), математических начертаний (𝑉) и пробелов между фрагментами
const norm = t => t.normalize('NFKC').toLowerCase()
let measureCtx = null
function frac (str, k) {
  if (k <= 0) return 0
  if (k >= str.length) return 1
  measureCtx ||= document.createElement('canvas').getContext('2d')
  measureCtx.font = '100px serif'
  const full = measureCtx.measureText(str).width
  return full ? measureCtx.measureText(str.slice(0, k)).width / full : k / str.length
}
// произведение матриц преобразования, как Util.transform в pdf.js
const mul = (a, b) => [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]]

function pageText (n) {
  if (!texts.has(n)) {
    texts.set(n, (async () => {
      const page = await doc.value.getPage(n)
      const vp = page.getViewport({ scale: 1 })
      const content = await page.getTextContent()
      const items = []
      const map = []
      let text = ''
      for (const it of content.items) {
        if (!it.str) continue
        const m = mul(vp.transform, it.transform)
        const lu = Math.hypot(m[0], m[1]) || 1
        const lv = Math.hypot(m[2], m[3]) || 1
        const k = items.length
        items.push({ str: it.str, o: [m[4], m[5]], u: [m[0] / lu, m[1] / lu], v: [m[2] / lv, m[3] / lv], w: it.width * vp.scale, h: lv })
        let ci = 0
        for (const cp of it.str) {
          for (const c of norm(cp)) if (!/\s/u.test(c)) { text += c; map.push([k, ci, cp.length]) }
          ci += cp.length
        }
      }
      return { text, map, items }
    })())
  }
  return texts.get(n)
}
// рамка куска фрагмента: от доли ширины a до b, по высоте от выносного элемента до нижнего
function segRect (item, a, b) {
  const pts = []
  for (const t of [a, b]) for (const up of [-0.22, 0.82]) {
    pts.push([item.o[0] + item.u[0] * t * item.w + item.v[0] * up * item.h, item.o[1] + item.u[1] * t * item.w + item.v[1] * up * item.h])
  }
  const xs = pts.map(p => p[0])
  const ys = pts.map(p => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}
function rectsFor (t, from, to) {
  const segs = new Map()
  for (let i = from; i < to; i++) {
    const [k, ci, len] = t.map[i]
    const sg = segs.get(k)
    if (sg) { sg.a = Math.min(sg.a, ci); sg.b = Math.max(sg.b, ci + len) } else segs.set(k, { a: ci, b: ci + len })
  }
  return [...segs.entries()].map(([k, sg]) => { const it = t.items[k]; return segRect(it, frac(it.str, sg.a), frac(it.str, sg.b)) })
}
async function runSearch () {
  const my = ++searchSeq
  const q = norm(query.value).replace(/\s+/gu, '')
  if (!q || !doc.value) { hits.value = []; hitIndex.value = -1; searching.value = false; return }
  searching.value = true
  const out = []
  for (const s of sizes.value) {
    const t = await pageText(s.n)
    if (my !== searchSeq) return
    for (let i = t.text.indexOf(q); i !== -1; i = t.text.indexOf(q, i + q.length)) out.push({ k: out.length, page: s.n, rects: rectsFor(t, i, i + q.length) })
  }
  hits.value = out
  searching.value = false
  const from = out.findIndex(h => h.page >= current.value)
  hitIndex.value = out.length ? Math.max(0, from) : -1
  if (hitIndex.value >= 0) goToHit(hitIndex.value)
}
function onQuery () {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(runSearch, 140)
}
function goToHit (k) {
  const h = hits.value[k]
  const pageEl = h && scroller.value?.querySelector(`[data-page="${h.page}"]`)
  if (!pageEl) return
  const r = h.rects[0]
  const top = pageEl.offsetTop + r[1] * scale.value
  const bottom = pageEl.offsetTop + r[3] * scale.value
  const sc = scroller.value
  const instant = matchMedia('(prefers-reduced-motion: reduce)').matches
  if (top < sc.scrollTop + 48 || bottom > sc.scrollTop + sc.clientHeight - 48) sc.scrollTo({ top: Math.max(0, top - sc.clientHeight * 0.35), behavior: instant ? 'auto' : 'smooth' })
  const left = pageEl.offsetLeft + r[0] * scale.value
  const right = pageEl.offsetLeft + r[2] * scale.value
  if (left < sc.scrollLeft || right > sc.scrollLeft + sc.clientWidth) sc.scrollTo({ left: Math.max(0, left - sc.clientWidth * 0.3), behavior: instant ? 'auto' : 'smooth' })
}
function stepHit (d) {
  if (!hits.value.length) return
  hitIndex.value = (hitIndex.value + d + hits.value.length) % hits.value.length
  goToHit(hitIndex.value)
}
function openFind () {
  findOpen.value = true
  nextTick(() => { findInput.value?.focus(); findInput.value?.select() })
  if (doc.value) for (const s of sizes.value) pageText(s.n)
  if (query.value.trim() && !hits.value.length) runSearch()
}
function closeFind () {
  findOpen.value = false
  searchSeq++
  hits.value = []
  hitIndex.value = -1
  searching.value = false
}
function onFindKey (e) {
  if (e.key === 'Enter') { e.preventDefault(); if (searching.value) return; stepHit(e.shiftKey ? -1 : 1) }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeFind() }
}
// Ctrl+F или ⌘F открывает поиск по статье; повторное нажатие в поле поиска отдаёт клавиши браузеру
function onGlobalKey (e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return
  if (e.code !== 'KeyF' && e.key.toLowerCase() !== 'f') return
  if (!sizes.value.length || error.value || !scroller.value?.offsetParent) return
  if (document.querySelector('[aria-modal="true"]')) return
  if (findOpen.value && document.activeElement === findInput.value) return
  e.preventDefault()
  openFind()
}
const hitsByPage = computed(() => {
  const m = {}
  for (const h of hits.value) (m[h.page] ||= []).push(h)
  return m
})
const findStatus = computed(() => {
  if (searching.value) return 'Ищу…'
  if (!query.value.trim()) return ''
  if (!hits.value.length) return 'Нет совпадений'
  return `${hitIndex.value + 1} из ${hits.value.length}`
})

function measure () {
  const w = (scroller.value?.clientWidth || 0) - 64
  fitWidth.value = props.margin ? Math.max(320, Math.min(w - GAP - NOTE_W, 820)) : Math.max(280, Math.min(w, 980))
}
function setZoom (z) {
  const keep = current.value
  zoom.value = Math.min(2.6, Math.max(0.6, z))
  nextTick(() => { scrollToFocus({ page: keep }, false); scroller.value?.querySelectorAll('[data-page]').forEach(el => { const r = el.getBoundingClientRect(); const s = scroller.value.getBoundingClientRect(); if (r.bottom > s.top - 400 && r.top < s.bottom + 400) renderPage(Number(el.dataset.page)) }) })
}

watch(() => props.documentId, () => open())
watch(() => props.focus, f => { if (f && sizes.value.length) nextTick(() => scrollToFocus(f)) })
watch(scale, () => { rendered.clear(); nextTick(() => io && observe()) })
watch(() => props.margin, () => nextTick(measure))

onMounted(() => {
  document.addEventListener('keydown', onGlobalKey)
  measure()
  ro = new ResizeObserver(() => measure())
  ro.observe(scroller.value)
  open()
})
onBeforeUnmount(() => { io?.disconnect(); ro?.disconnect(); document.removeEventListener('keydown', onGlobalKey); clearTimeout(searchTimer) })
defineExpose({ scrollToFocus })
</script>

<template>
  <div class="pdfv">
    <div class="pdfv__bar">
      <span class="pdfv__page num" aria-live="polite">{{ sizes.length ? `Стр. ${current} из ${sizes.length}` : 'PDF' }}</span>
      <span class="grow" />
      <div v-if="findOpen" class="pdfv__find" role="search">
        <label class="pdfv__findbox">
          <Search aria-hidden="true" />
          <input ref="findInput" v-model="query" class="input input--sm" type="search" placeholder="Найти в статье" aria-label="Найти в статье" autocomplete="off" spellcheck="false" @input="onQuery" @keydown="onFindKey">
        </label>
        <span class="pdfv__count num" aria-live="polite">{{ findStatus }}</span>
        <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Предыдущее совпадение" title="Предыдущее (Shift+Enter)" :disabled="!hits.length" @click="stepHit(-1)"><ChevronUp /></button>
        <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Следующее совпадение" title="Следующее (Enter)" :disabled="!hits.length" @click="stepHit(1)"><ChevronDown /></button>
        <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Закрыть поиск" title="Закрыть (Esc)" @click="closeFind"><X /></button>
      </div>
      <button v-else class="btn btn--ghost btn--icon btn--sm pdfv__findbtn" type="button" aria-label="Найти в статье" :title="`Найти в статье (${findKey})`" :disabled="!sizes.length" @click="openFind"><Search /></button>
      <span class="pdfv__sep" aria-hidden="true" />
      <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Уменьшить" title="Уменьшить" :disabled="!sizes.length" @click="setZoom(zoom - 0.2)"><ZoomOut /></button>
      <button class="pdfv__zoom num" type="button" title="По ширине" :disabled="!sizes.length" @click="setZoom(1)">{{ Math.round(zoom * 100) }} %</button>
      <button class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Увеличить" title="Увеличить" :disabled="!sizes.length" @click="setZoom(zoom + 0.2)"><ZoomIn /></button>
    </div>
    <div ref="scroller" class="pdfv__scroll" @scroll.passive="onScroll">
      <div v-if="error" class="pdfv__error">
        <FileWarning />
        <p>{{ error }}</p>
      </div>
      <div v-else class="pdfv__desk" :class="{ 'has-margin': margin }">
        <div class="pdfv__pages">
          <div v-if="loading" class="pdfv__sheet skeleton" :style="{ width: `${fitWidth}px`, height: `${fitWidth * 1.41}px` }" />
          <template v-else>
          <div v-for="s in sizes" :key="s.n" class="pdfv__sheet" :data-page="s.n" :style="pageStyle(s)">
            <canvas />
            <div class="pdfv__paper" />
            <span v-for="h in hitsByPage[s.n] || []" :key="`hit-${h.k}`" class="pdfv__hits" aria-hidden="true">
              <span v-for="(r, i) in h.rects" :key="i" class="hit" :class="{ 'is-current': h.k === hitIndex }" :style="rectStyle(r, s)" />
            </span>
            <button
              v-for="b in boxesByPage[s.n] || []" :key="b.id" type="button" class="pin"
              :class="[`pin--${b.tone || 'idle'}`, { 'is-active': b.id === activeId }]"
              :style="boxStyle(b, s)" :aria-label="b.label" :title="b.label"
              @click="emit('select', b.id)"
            />
            <span v-if="margin && activeBox && activeBox.page === s.n && $slots.note" :key="`lead-${activeId}`" class="pdfv__lead" :style="leadStyle" aria-hidden="true" />
          </div>
          </template>
        </div>
        <aside v-if="margin" class="pdfv__margin">
          <div v-if="$slots.note && activeId" :key="`note-${activeId}`" class="pdfv__note" :class="{ 'is-loose': !activeBox }" :style="noteStyle"><slot name="note" /></div>
          <p v-else-if="!loading" class="pdfv__hint">Нажмите на число на странице или в списке справа: здесь появится заметка с условиями и источником.</p>
        </aside>
      </div>
    </div>
  </div>
</template>

<style>
.pdfv { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.pdfv__bar { display: flex; align-items: center; gap: 2px; height: 40px; flex: none; padding: 0 12px 0 32px; }
.pdfv__page { color: var(--pencil); font-size: 13px; }
.pdfv__zoom { min-width: 52px; height: 28px; padding: 0 4px; border: 0; border-radius: 6px; background: none; color: var(--pencil); font-size: 13px; }
.pdfv__zoom:hover { color: var(--ink); background: var(--hover); }
.pdfv__scroll { flex: 1; overflow: auto; position: relative; overscroll-behavior: contain; }
.pdfv__find { display: flex; align-items: center; gap: 2px; }
.pdfv__findbox { position: relative; display: flex; align-items: center; }
.pdfv__findbox svg { position: absolute; left: 9px; width: 14px; height: 14px; color: var(--pencil); pointer-events: none; }
.pdfv__findbox .input { width: 220px; height: 28px; padding-left: 30px; }
.pdfv__findbox .input::-webkit-search-cancel-button { display: none; }
.pdfv__count { min-width: 112px; padding: 0 10px; font-size: 13px; color: var(--pencil); text-align: left; white-space: nowrap; }
.pdfv__sep { width: 1px; height: 16px; margin: 0 8px; background: var(--rule-mid); }
/* совпадения поиска: графит поверх бумаги, текущее обведено; цвет не спорит с зелёным источником и охрой замечаний */
.hit { position: absolute; border-radius: 2px; background: rgb(28 28 28 / .16); pointer-events: none; }
.hit.is-current { background: rgb(28 28 28 / .2); box-shadow: 0 0 0 1.5px #1C1C1C; }
.pdfv__desk { display: grid; grid-template-columns: max-content; justify-content: center; padding: 4px 32px 48px; min-width: min-content; }
.pdfv__desk.has-margin { grid-template-columns: max-content 300px; column-gap: 40px; }
.pdfv__pages { display: flex; flex-direction: column; gap: 24px; }
.pdfv__sheet { position: relative; flex: none; background: #fff; border-radius: 2px; box-shadow: 0 1px 2px var(--shade), 0 16px 36px -18px var(--shade); }
.pdfv__sheet canvas { position: absolute; inset: 0; width: 100%; height: 100%; border-radius: 2px; }
.pdfv__paper { position: absolute; inset: 0; background: var(--paper); mix-blend-mode: multiply; pointer-events: none; border-radius: 2px; }
.pdfv__error { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; max-width: 420px; margin: 80px 32px; color: var(--pencil); }
.pdfv__error svg { width: 22px; height: 22px; color: var(--danger); }

.pdfv__margin { position: relative; }
.pdfv__note { position: absolute; left: 0; width: 300px; z-index: 3; animation: note-in 240ms var(--spring) 180ms both; }
.pdfv__note.is-loose { position: sticky; top: 12px; }
.pdfv__hint { position: sticky; top: 12px; max-width: 260px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.pdfv__lead { position: absolute; z-index: 2; height: 1.5px; margin-top: -0.75px; background: #07854A; transform-origin: left center; pointer-events: none; animation: lead-in 220ms var(--ease) 90ms both; }
@keyframes note-in { from { opacity: 0; transform: translateX(-8px); } }
@keyframes lead-in { from { transform: scaleX(0); } }

/* рамка источника: у выбранного числа зелёная; у числа с замечанием охра или красный; остальные видны при наведении на страницу */
.pin { position: absolute; padding: 0; margin: 0; border: 0; background: transparent; border-radius: 2px; transform: scale(1.1); transition: box-shadow 160ms var(--ease), background-color 160ms var(--ease); }
.pdfv__sheet:hover .pin--idle { box-shadow: 0 0 0 1px rgb(7 133 74 / .4); }
.pin--idle:hover { box-shadow: 0 0 0 1.5px #07854A !important; background: rgb(7 133 74 / .08); }
.pin--warn { box-shadow: 0 0 0 1.5px rgb(183 121 31 / .85); }
.pin--error { box-shadow: 0 0 0 1.5px rgb(196 67 47 / .8); }
.pin.is-active { z-index: 2; box-shadow: 0 0 0 2px #07854A; background: rgb(7 133 74 / .1); animation: frame-in 200ms var(--ease) both; }
.pin.is-active.pin--warn { box-shadow: 0 0 0 2px #07854A, 0 0 0 4px rgb(183 121 31 / .55); }
.pin.is-active.pin--error { box-shadow: 0 0 0 2px #07854A, 0 0 0 4px rgb(196 67 47 / .5); }
@keyframes frame-in { from { box-shadow: 0 0 0 0 #07854A; background: transparent; } }
@media (prefers-reduced-motion: reduce) { .pin.is-active, .pdfv__note, .pdfv__lead { animation: none; } }
</style>
