<!-- Назначение файла: результаты корпуса одной таблицей (GET /corpora/{id}/results): поиск, фильтры по показателю,
     агрегации, происхождению и замечаниям, выбор строк и сравнение. Строка открывает статью на этом значении. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, GitCompare, X } from '@lucide/vue'
import Segmented from '../components/ui/Segmented.vue'
import Metric from '../components/ui/Metric.vue'
import CompareDrawer from '../components/app/CompareDrawer.vue'
import { catalog } from '../api/index.js'
import { ws } from '../stores/workspace.js'
import { notify } from '../stores/toasts.js'
import { profileTitle, valueLabel } from '../lib/labels.js'
import { fmtNum, fmtResult, countText } from '../lib/format.js'

const router = useRouter()
const profile = ref('solar-v1')
const q = ref('')
const metric = ref('')
const aggregation = ref('')
const origin = ref('')
const issuesOnly = ref(false)
const sort = ref({ key: 'publication_code', dir: 'asc' })
const rows = ref([])
const total = ref(0)
const facets = ref({ metrics: [] })
const loading = ref(true)
const selected = ref(new Map())
const compareOpen = ref(false)

let seq = 0
async function load () {
  const my = ++seq
  loading.value = true
  try {
    const res = await catalog.results(ws.corpus.id, {
      profile: profile.value, q: q.value.trim(), metric: metric.value, aggregation: aggregation.value, origin: origin.value,
      has_issues: issuesOnly.value ? 'true' : undefined, sort: sort.value.key, order: sort.value.dir, page_size: 200
    })
    if (my !== seq) return
    rows.value = res.items
    total.value = res.total
    facets.value = res.facets || facets.value
  } catch (e) { notify.error(e) } finally { if (my === seq) loading.value = false }
}
onMounted(load)
let t = null
watch(q, () => { clearTimeout(t); t = setTimeout(load, 250) })
watch([metric, aggregation, origin, issuesOnly, sort], load, { deep: true })
watch(profile, () => { metric.value = ''; aggregation.value = ''; origin.value = ''; selected.value.clear(); load() })

const key = r => `${r.publication_id}|${r.result_id}`
function toggle (r) { selected.value.has(key(r)) ? selected.value.delete(key(r)) : selected.value.set(key(r), r) }
const allOn = computed(() => rows.value.length > 0 && rows.value.every(r => selected.value.has(key(r))))
function toggleAll () {
  if (allOn.value) rows.value.forEach(r => selected.value.delete(key(r)))
  else rows.value.forEach(r => selected.value.set(key(r), r))
}
const refs = computed(() => [...selected.value.values()].map(r => ({ publication_id: r.publication_id, result_id: r.result_id })))
function sortBy (k) { sort.value = { key: k, dir: sort.value.key === k && sort.value.dir === 'asc' ? 'desc' : 'asc' } }
function reset () { q.value = ''; metric.value = ''; aggregation.value = ''; origin.value = ''; issuesOnly.value = false }
const filtered = computed(() => q.value || metric.value || aggregation.value || origin.value || issuesOnly.value)
function open (r) {
  router.push({ name: 'article', params: { corpusId: ws.corpus.id, documentId: r.document_id }, query: { profile: r.profile, record: r.result_id } })
}
function conditions (r) {
  const c = r.context
  if (r.profile === 'solar-v1') {
    return [c.spectrum && c.intensity ? `${c.spectrum}, ${fmtNum(c.intensity)} мВт/см²` : null, c.area ? `${fmtNum(c.area)} см²` : null, c.scan_direction ? `${valueLabel('scan_direction', c.scan_direction)}` : (c.measurement_type === 'J-V' ? 'развёртка не указана' : null), c.certified ? 'сертифицировано' : null].filter(Boolean).join(', ')
  }
  return [c.retrieval, c.chunk_size ? `фрагмент ${c.chunk_size}` : null, c.top_k !== null && c.top_k !== undefined ? `top_k ${c.top_k}` : null, c.reranker].filter(Boolean).join(', ')
}
const isSolar = computed(() => profile.value === 'solar-v1')
const arrow = k => sort.value.key === k ? (sort.value.dir === 'asc' ? '↑' : '↓') : ''
</script>

<template>
  <div class="page res">
    <div class="page__head">
      <h1 class="page__title">Результаты<span class="count">{{ total }}</span></h1>
      <span class="grow" />
      <Segmented v-model="profile" :options="[{ value: 'solar-v1', label: 'Солнечные элементы' }, { value: 'rag-v1', label: 'RAG-системы' }]" label="Профиль" />
    </div>

    <div class="res__filters">
      <label class="res__search">
        <Search />
        <input v-model="q" class="input input--sm" type="search" :placeholder="isSolar ? 'Статья, материал, прибор' : 'Статья, модель, набор данных'" aria-label="Поиск по результатам">
      </label>
      <select v-model="metric" class="select select--sm res__sel" aria-label="Показатель">
        <option value="">Все показатели</option>
        <option v-for="m in facets.metrics" :key="m" :value="m">{{ m }}</option>
      </select>
      <select v-if="isSolar" v-model="aggregation" class="select select--sm res__sel" aria-label="Агрегация">
        <option value="">Любая агрегация</option>
        <option value="champion">лучший прибор</option>
        <option value="mean">среднее</option>
      </select>
      <select v-model="origin" class="select select--sm res__sel" aria-label="Происхождение">
        <option value="">Свои и цитаты</option>
        <option value="primary">только из статьи</option>
        <option value="cited">только цитаты</option>
      </select>
      <label class="check res__check"><input v-model="issuesOnly" type="checkbox">С замечаниями</label>
      <button v-if="filtered" class="btn btn--ghost btn--sm" type="button" @click="reset"><X />Сбросить</button>
    </div>

    <div class="panel res__table">
      <table class="table">
        <thead>
          <tr>
            <th class="t-check"><input type="checkbox" class="cb" :checked="allOn" aria-label="Выбрать все" @change="toggleAll"></th>
            <th><button class="th-sort" type="button" @click="sortBy('publication_code')">Статья {{ arrow('publication_code') }}</button></th>
            <th><button class="th-sort" type="button" @click="sortBy('metric_name')">{{ isSolar ? 'Показатель' : 'Метрика' }} {{ arrow('metric_name') }}</button></th>
            <th class="t-num"><button class="th-sort" type="button" @click="sortBy('metric_value')">Значение {{ arrow('metric_value') }}</button></th>
            <th>{{ isSolar ? 'Прибор' : 'Конфигурация' }}</th>
            <th>{{ isSolar ? 'Условия' : 'Набор данных' }}</th>
            <th>Источник</th>
            <th class="t-num">Замечания</th>
          </tr>
        </thead>
        <tbody v-if="!loading || rows.length">
          <tr v-for="r in rows" :key="key(r)" class="is-link" :class="{ 'is-selected': selected.has(key(r)) }" @click="open(r)">
            <td class="t-check" @click.stop><input type="checkbox" class="cb" :checked="selected.has(key(r))" :aria-label="`Выбрать ${r.publication_code} ${r.result_id}`" @change="toggle(r)"></td>
            <td class="nowrap"><b>{{ r.publication_code }}</b> <span class="faint">{{ r.result_id }}</span><span v-if="r.origin === 'cited'" class="chip chip--plain res__cited">цитата</span></td>
            <td class="nowrap"><Metric :name="r.metric_name" :k="r.metric_k" /><span v-if="r.aggregation && r.aggregation !== 'champion'" class="muted">, {{ valueLabel('aggregation', r.aggregation) }}</span></td>
            <td class="t-num"><b class="res__val">{{ fmtResult(r) }}</b></td>
            <td class="res__ctx">{{ isSolar ? r.context.device : `${r.context.config || '–'}${r.context.retrieval ? ', ' + r.context.retrieval : ''}` }}</td>
            <td class="res__ctx muted">{{ isSolar ? conditions(r) : [r.context.dataset, r.context.split].filter(Boolean).join(', ') }}</td>
            <td class="nowrap"><span v-if="r.source.has_evidence" class="muted">стр. {{ r.source.page }}<template v-if="r.source.table">, {{ r.source.table }}</template><template v-else-if="r.source.figure">, {{ r.source.figure }}</template></span><span v-else class="res__nosrc">нет источника</span></td>
            <td class="t-num"><span v-if="r.issues_open" class="count count--warn">{{ r.issues_open }}</span><span v-else class="faint">–</span></td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !rows.length" class="empty">{{ filtered ? 'Под фильтры ничего не подходит.' : `В профиле «${profileTitle(profile)}» пока нет результатов.` }}</p>
    </div>

    <Transition name="selbar">
      <div v-if="selected.size" class="selbar" role="region" aria-label="Выбранные результаты">
        <span>Выбрано {{ countText(selected.size, ['результат', 'результата', 'результатов']) }}</span>
        <span class="grow" />
        <button class="btn btn--ghost btn--sm selbar__clear" type="button" @click="selected.clear()">Снять выбор</button>
        <button class="btn btn--primary btn--sm" type="button" :disabled="selected.size < 2" @click="compareOpen = true"><GitCompare />Сравнить</button>
      </div>
    </Transition>
    <CompareDrawer :open="compareOpen" :corpus-id="ws.corpus.id" :profile="profile" :refs="refs" @close="compareOpen = false" />
  </div>
</template>

<style>
.res__filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: var(--s-3); }
.res__search { position: relative; display: flex; align-items: center; }
.res__search svg { position: absolute; left: 9px; width: 15px; height: 15px; color: var(--muted); }
.res__search .input { width: 260px; padding-left: 30px; }
.res__sel { width: auto; min-width: 150px; }
.res__check { font-size: var(--fs-sm); margin-left: 4px; }
.res__table { overflow: auto; margin-bottom: 72px; }
.res__val { font-weight: 500; }
.res__ctx { max-width: 280px; }
.res__cited { margin-left: 6px; }
.res__nosrc { color: var(--danger); font-size: var(--fs-sm); }
.th-sort { padding: 0; border: 0; background: none; color: inherit; font: inherit; cursor: pointer; }
.th-sort:hover { color: var(--ink); }
.selbar { position: fixed; left: 50%; bottom: 20px; z-index: 35; display: flex; align-items: center; gap: 12px; width: min(560px, calc(100vw - 32px)); padding: 8px 8px 8px 18px; transform: translateX(-50%); background: var(--ink); color: var(--bg); border-radius: var(--r-lg); box-shadow: var(--shadow-overlay); font-weight: 500; }
.selbar__clear { color: inherit; }
.selbar__clear:hover { background: rgba(255, 255, 255, .12); }
[data-theme="dark"] .selbar__clear:hover { background: rgba(0, 0, 0, .08); }
.selbar-enter-active, .selbar-leave-active { transition: opacity .18s var(--ease), transform .18s var(--ease); }
.selbar-enter-from, .selbar-leave-to { opacity: 0; transform: translate(-50%, 8px); }
</style>
