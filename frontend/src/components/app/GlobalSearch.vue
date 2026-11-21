<!-- Назначение файла: поиск по корпусу: метаданные и текст страниц (GET /corpora/{id}/search).
     Результат открывает статью на найденной странице. На телефоне поле раскрывается на весь экран. -->
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, X } from '@lucide/vue'
import { catalog, snippetParts } from '../../api/index.js'

const props = defineProps({ corpusId: String, compact: Boolean })
const router = useRouter()
const q = ref('')
const open = ref(false)
const expanded = ref(false)
const loading = ref(false)
const items = ref([])
const active = ref(0)
const root = ref(null)
const input = ref(null)
let timer = null
let seq = 0

watch(q, v => {
  clearTimeout(timer)
  if (v.trim().length < 2) { items.value = []; loading.value = false; return }
  loading.value = true
  timer = setTimeout(async () => {
    const my = ++seq
    try {
      const res = await catalog.search(props.corpusId, { q: v.trim(), scope: 'all', page_size: 20 })
      if (my === seq) { items.value = res.items; active.value = 0 }
    } catch { if (my === seq) items.value = [] } finally { if (my === seq) loading.value = false }
  }, 220)
})
const shown = computed(() => items.value.slice(0, 12))
function go (it) {
  if (!it) return
  router.push({ name: 'article', params: { corpusId: props.corpusId, documentId: it.document_id }, query: it.page ? { page: it.page } : {} })
  close()
}
function close () { open.value = false; expanded.value = false; q.value = '' }
function onKey (e) {
  if (e.key === 'ArrowDown') { active.value = Math.min(shown.value.length - 1, active.value + 1); e.preventDefault() }
  if (e.key === 'ArrowUp') { active.value = Math.max(0, active.value - 1); e.preventDefault() }
  if (e.key === 'Enter') go(shown.value[active.value])
  if (e.key === 'Escape') close()
}
function onDoc (e) { if (!root.value?.contains(e.target)) open.value = false }
function onSlash (e) {
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) { e.preventDefault(); input.value?.focus() }
}
document.addEventListener('mousedown', onDoc)
document.addEventListener('keydown', onSlash)
onBeforeUnmount(() => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onSlash) })
function expand () { expanded.value = true; setTimeout(() => input.value?.focus(), 30) }
</script>

<template>
  <div ref="root" class="gsearch" :class="{ 'is-compact': compact, 'is-expanded': expanded }">
    <button v-if="compact && !expanded" class="btn btn--ghost btn--icon" type="button" aria-label="Поиск по статьям" @click="expand"><Search /></button>
    <template v-if="!compact || expanded">
      <label class="gsearch__box">
        <Search class="gsearch__icon" />
        <input ref="input" v-model="q" class="gsearch__input" type="search" placeholder="Поиск по тексту статей" aria-label="Поиск по тексту статей" autocomplete="off" @focus="open = true" @keydown="onKey">
        <kbd v-if="!compact && !q" class="gsearch__kbd">/</kbd>
        <button v-if="compact" class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Закрыть поиск" @click="close"><X /></button>
      </label>
      <div v-if="(open || expanded) && q.trim().length >= 2" class="gsearch__panel" role="listbox">
        <p v-if="loading && !shown.length" class="gsearch__note">Ищу…</p>
        <p v-else-if="!shown.length" class="gsearch__note">Ничего не найдено. Поиск идёт по названиям, DOI, авторам и тексту страниц.</p>
        <button v-for="(it, i) in shown" :key="`${it.document_id}-${it.page}-${i}`" type="button" class="gsearch__item" :class="{ 'is-active': i === active }" role="option" @mouseenter="active = i" @click="go(it)">
          <span class="gsearch__meta"><b>{{ it.publication_code }}</b><span class="ellipsis">{{ it.title }}</span><span class="gsearch__page">{{ it.page ? `стр. ${it.page}` : 'метаданные' }}</span></span>
          <span class="gsearch__snip"><template v-for="(p, k) in snippetParts(it.snippet)" :key="k"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></span>
        </button>
      </div>
    </template>
  </div>
</template>

<style>
.gsearch { position: relative; }
.gsearch__box { display: flex; align-items: center; gap: 8px; width: 300px; height: 34px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: var(--r-md); background: var(--surface-2); cursor: text; }
.gsearch__box:focus-within { border-color: var(--accent); box-shadow: var(--focus); }
.gsearch__icon { width: 16px; height: 16px; color: var(--muted); flex: none; }
.gsearch__input { flex: 1; min-width: 0; border: 0; background: none; outline: none; font-size: var(--fs-md); }
.gsearch__input::-webkit-search-cancel-button { display: none; }
.gsearch__kbd { padding: 0 6px; border: 1px solid var(--line-strong); border-radius: 4px; font: 500 11px/18px var(--font); color: var(--muted); }
.gsearch__panel { position: absolute; top: calc(100% + 6px); right: 0; z-index: 45; width: min(560px, 92vw); max-height: 70vh; overflow: auto; padding: 6px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--shadow-overlay); }
.gsearch__note { padding: 12px; color: var(--muted); font-size: var(--fs-sm); }
.gsearch__item { display: block; width: 100%; padding: 9px 10px; border: 0; border-radius: var(--r-sm); background: none; text-align: left; cursor: pointer; }
.gsearch__item.is-active { background: var(--surface-hover); }
.gsearch__meta { display: flex; align-items: baseline; gap: 8px; font-size: var(--fs-sm); color: var(--muted); }
.gsearch__meta b { color: var(--ink); font-weight: 600; flex: none; }
.gsearch__meta .ellipsis { flex: 1; }
.gsearch__page { flex: none; }
.gsearch__snip { display: block; margin-top: 3px; font-size: var(--fs-sm); color: var(--ink-2); line-height: 1.4; }
.gsearch__snip mark { background: var(--accent-soft); color: var(--accent-text); border-radius: 2px; padding: 0 1px; }
.gsearch.is-compact.is-expanded { position: fixed; inset: 0 0 auto 0; z-index: 46; padding: 8px 12px; background: var(--bg); border-bottom: 1px solid var(--line); }
.gsearch.is-compact.is-expanded .gsearch__box { width: 100%; height: 40px; }
.gsearch.is-compact.is-expanded .gsearch__panel { position: fixed; left: 8px; right: 8px; top: 60px; width: auto; max-height: calc(100vh - 140px); }
@media (max-width: 1180px) { .gsearch:not(.is-compact) .gsearch__box { width: 220px; } }
</style>
