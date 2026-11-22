<!-- Назначение файла: результаты корпуса одной таблицей (GET /corpora/{id}/results): поиск, фильтры по показателю,
     агрегации, происхождению и замечаниям, выбор строк и сравнение. Строка открывает статью на этом значении. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@lucide/vue'
import Segmented from '../components/ui/Segmented.vue'
import Metric from '../components/ui/Metric.vue'
import CompareDrawer from '../components/app/CompareDrawer.vue'
import { catalog } from '../api/index.js'
import { ws } from '../stores/workspace.js'
import { notify } from '../stores/toasts.js'
import { profileTitle, valueLabel } from '../lib/labels.js'
import { fmtResult, countText } from '../lib/format.js'
import { resultDevice, resultConditions, resultSetup } from '../lib/rowline.js'

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
const isSolar = computed(() => profile.value === 'solar-v1')
const arrow = k => sort.value.key === k ? (sort.value.dir === 'asc' ? '↑' : '↓') : ''
</script>

<template>
  <div class="page res">
    <div class="page__head">
      <h1 class="page__title">Результаты</h1>
      <Segmented v-model="profile" :options="[{ value: 'solar-v1', label: 'Солнечные элементы' }, { value: 'rag-v1', label: 'RAG-системы' }]" label="Профиль" />
      <span class="grow" />
      <span v-if="!loading" class="res__total">{{ countText(total, ['значение', 'значения', 'значений']) }}</span>
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
      <label class="check res__check"><input v-model="issuesOnly" type="checkbox" class="cb">С замечаниями</label>
      <button v-if="filtered" class="btn btn--ghost btn--sm" type="button" @click="reset">Сбросить</button>
    </div>

    <table class="table res__table">
      <thead>
        <tr>
          <th class="t-check"><input type="checkbox" class="cb" :checked="allOn" aria-label="Выбрать все" @change="toggleAll"></th>
          <th class="res__c-pub"><button class="th-sort" :class="{ 'is-on': sort.key === 'publication_code' }" type="button" @click="sortBy('publication_code')">Статья<span class="th-sort__dir">{{ arrow('publication_code') }}</span></button></th>
          <th><button class="th-sort" :class="{ 'is-on': sort.key === 'metric_name' }" type="button" @click="sortBy('metric_name')">{{ isSolar ? 'Показатель' : 'Метрика' }}<span class="th-sort__dir">{{ arrow('metric_name') }}</span></button></th>
          <th class="t-num"><button class="th-sort" :class="{ 'is-on': sort.key === 'metric_value' }" type="button" @click="sortBy('metric_value')">Значение<span class="th-sort__dir">{{ arrow('metric_value') }}</span></button></th>
          <th v-if="isSolar" class="res__c-dev">Прибор</th>
          <th class="res__c-ctx">{{ isSolar ? 'Условия измерения' : 'Конфигурация и данные' }}</th>
          <th class="res__c-src">Источник</th>
        </tr>
      </thead>
      <tbody v-if="loading && !rows.length">
        <tr v-for="i in 8" :key="i"><td /><td><span class="skeleton" style="width: 64px; height: 14px" /></td><td><span class="skeleton" style="width: 48px; height: 14px" /></td><td class="t-num"><span class="skeleton" style="width: 56px; height: 14px; margin-left: auto" /></td><td v-if="isSolar"><span class="skeleton" style="width: 80px; height: 14px" /></td><td><span class="skeleton" style="width: 60%; height: 14px" /></td><td><span class="skeleton" style="width: 64px; height: 14px" /></td></tr>
      </tbody>
      <tbody v-else>
        <tr v-for="r in rows" :key="key(r)" class="is-link" :class="{ 'is-selected': selected.has(key(r)) }" @click="open(r)">
          <td class="t-check" @click.stop><input type="checkbox" class="cb" :checked="selected.has(key(r))" :aria-label="`Выбрать ${r.publication_code} ${r.result_id}`" @change="toggle(r)"></td>
          <td class="nowrap"><b>{{ r.publication_code }}</b><span class="res__id">{{ r.result_id }}</span><span v-if="r.origin === 'cited'" class="res__cited">цитата</span></td>
          <td class="nowrap"><Metric :name="r.metric_name" :k="r.metric_k" /><span v-if="r.aggregation && r.aggregation !== 'champion'" class="muted">, {{ valueLabel('aggregation', r.aggregation) }}</span></td>
          <td class="t-num">
            <span class="res__val" :class="{ flag: r.issues_open }" :title="r.issues_open ? `Открытых замечаний: ${r.issues_open}` : null">{{ fmtResult(r) }}</span>
            <span v-if="r.issues_open" class="visually-hidden">, есть замечания</span>
          </td>
          <td v-if="isSolar" class="res__dev">{{ resultDevice(r) }}</td>
          <td v-if="isSolar" class="res__ctx" :title="resultConditions(r)">{{ resultConditions(r) }}</td>
          <td v-else class="res__ctx" :title="[resultSetup(r).head, resultSetup(r).rest].filter(Boolean).join(', ')"><span class="res__dev">{{ resultSetup(r).head }}</span><span class="res__cond">{{ resultSetup(r).rest }}</span></td>
          <td class="nowrap res__src"><template v-if="r.source.has_evidence">стр. {{ r.source.page }}<template v-if="r.source.table">, {{ r.source.table }}</template><template v-else-if="r.source.figure">, {{ r.source.figure }}</template></template><span v-else class="res__nosrc">без источника</span></td>
        </tr>
      </tbody>
    </table>
    <div v-if="!loading && !rows.length" class="empty">
      <h3>{{ filtered ? 'Под фильтры ничего не подходит' : 'Результатов пока нет' }}</h3>
      <p v-if="filtered">Измените условия или сбросьте фильтры.</p>
      <p v-else>В профиле «{{ profileTitle(profile) }}» появятся значения после обработки статей.</p>
      <button v-if="filtered" class="btn" type="button" @click="reset">Сбросить фильтры</button>
    </div>

    <Transition name="selbar">
      <div v-if="selected.size" class="selbar" role="region" aria-label="Выбранные результаты">
        <span class="selbar__n">Выбрано {{ countText(selected.size, ['значение', 'значения', 'значений']) }}</span>
        <span class="grow" />
        <button class="btn btn--ghost btn--sm" type="button" @click="selected.clear()">Снять выбор</button>
        <button class="btn btn--accent btn--sm" type="button" :disabled="selected.size < 2" :title="selected.size < 2 ? 'Выберите минимум два значения' : null" @click="compareOpen = true">Сравнить</button>
      </div>
    </Transition>
    <CompareDrawer :open="compareOpen" :corpus-id="ws.corpus.id" :profile="profile" :refs="refs" @close="compareOpen = false" />
  </div>
</template>

<style>
/* результаты: таблица как в статье, значение с замечанием подчёркнуто волной корректора */
.res__total { color: var(--pencil); }
.res__filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.res__search { position: relative; display: flex; align-items: center; }
.res__search svg { position: absolute; left: 10px; width: 15px; height: 15px; color: var(--pencil); pointer-events: none; }
.res__search .input { width: 280px; padding-left: 32px; }
.res__sel { width: auto; min-width: 156px; }
.res__check { margin-left: 8px; color: var(--pencil); }
.res__table { margin-bottom: 96px; }
.res__c-pub { width: 150px; }
.res__c-src { width: 150px; }
.res__id { margin-left: 8px; color: var(--pencil); }
.res__cited { margin-left: 8px; font-size: 13px; color: var(--pencil); }
.res__val { font-weight: 400; }
.res__ctx { max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.res__c-dev { width: 170px; }
.res__dev { white-space: nowrap; }
td.res__ctx { color: var(--ink); }
.res__cond { margin-left: 8px; color: var(--pencil); }
.res__src { color: var(--pencil); font-size: 13px; }
.res__nosrc { color: var(--danger); }
.th-sort { display: inline-flex; align-items: baseline; gap: 4px; padding: 0; border: 0; background: none; color: inherit; font: inherit; }
.th-sort:hover, .th-sort.is-on { color: var(--ink); }
.th-sort__dir { min-width: .6em; }
.selbar { position: fixed; left: 50%; bottom: 24px; z-index: 35; display: flex; align-items: center; gap: 8px; width: min(560px, calc(100vw - 32px)); padding: 8px 8px 8px 18px; transform: translateX(-50%); background: var(--float); color: var(--ink); border-radius: 10px; box-shadow: var(--shadow); }
.selbar__n { font-weight: 600; }
.selbar-enter-active, .selbar-leave-active { transition: opacity 180ms var(--ease), transform 260ms var(--spring); }
.selbar-enter-from, .selbar-leave-to { opacity: 0; transform: translate(-50%, 10px); }
</style>
