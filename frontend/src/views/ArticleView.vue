<!-- Назначение файла: статья: слева PDF с рамками источников, справа записи профиля по типам сущностей.
     Клик по записи листает PDF к её месту и обводит число; клик по рамке выбирает запись. Правки создают
     новую версию графа (If-Match), после правок можно сразу пересчитать замечания. На телефоне: список
     записей и карточка с вырезкой страницы, без PDF целиком и без правки значений. -->
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronLeft, History, Plus, RefreshCw, CircleAlert, Hourglass, FileX, Ban } from '@lucide/vue'
import PdfViewer from '../components/app/PdfViewer.vue'
import RecordDetail from '../components/app/RecordDetail.vue'
import EntityForm from '../components/app/EntityForm.vue'
import HistoryDrawer from '../components/app/HistoryDrawer.vue'
import ClassificationDialog from '../components/app/ClassificationDialog.vue'
import Drawer from '../components/ui/Drawer.vue'
import Chip from '../components/ui/Chip.vue'
import Metric from '../components/ui/Metric.vue'
import Segmented from '../components/ui/Segmented.vue'
import Progress from '../components/ui/Progress.vue'
import { documents, publications, catalog, jobs } from '../api/index.js'
import { ws, kickJobs } from '../stores/workspace.js'
import { canEdit } from '../stores/session.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { ENTITY, RESULT_ENTITY, ID_FIELD, DOC_STATUS, STAGE, LABEL_TO_PROFILE, profileTitle, profileShort, valueLabel } from '../lib/labels.js'
import { sortItems, rowText, evidenceOf, pinLabel } from '../lib/records.js'
import { fmtValue, fmtNum, fmtResult } from '../lib/format.js'

const props = defineProps({ corpusId: String, documentId: String })
const route = useRoute()
const router = useRouter()

const doc = ref(null)
const pub = ref(null)
const profile = ref(null)
const graph = ref(null)
const etag = ref(null)
const issues = ref([])
const loading = ref(true)
const type = ref(null)
const selectedId = ref(null)
const focus = ref(null)
const onlyIssues = ref(false)
const historyOpen = ref(false)
const form = ref({ open: false, mode: 'edit', item: null })
const decideOpen = ref(false)
const needsRecheck = ref(false)
const recheckJob = ref(null)
const listEl = ref(null)
const editable = computed(() => canEdit(ws.corpus))

async function load () {
  loading.value = true
  try {
    doc.value = await documents.get(props.documentId)
    pub.value = doc.value.publication_id ? await publications.get(doc.value.publication_id) : null
    const profiles = pub.value ? Object.keys(pub.value.profiles) : []
    profile.value = profiles.includes(route.query.profile) ? route.query.profile : profiles[0] || null
    await Promise.all([loadGraph(), loadIssues()])
    applyQuery()
  } catch (e) {
    notify.error(e)
  } finally {
    loading.value = false
  }
}
async function loadGraph () {
  graph.value = null
  if (!pub.value || !profile.value) return
  const res = await publications.graph(pub.value.id, profile.value)
  graph.value = res.data
  etag.value = res.etag
  const types = Object.keys(graph.value.entities)
  if (!types.includes(type.value)) type.value = types.includes(route.query.entity) ? route.query.entity : RESULT_ENTITY[profile.value]
}
async function loadIssues () {
  if (!pub.value) { issues.value = []; return }
  const res = await catalog.issues(props.corpusId, { publication_id: pub.value.id })
  issues.value = res.items
}
function applyQuery () {
  const rec = route.query.record
  if (rec && graph.value) {
    if (route.query.entity && graph.value.entities[route.query.entity]) type.value = route.query.entity
    select(String(rec), false)
  } else if (route.query.page) {
    focus.value = { page: Number(route.query.page) }
  }
}
watch(() => props.documentId, () => { selectedId.value = null; type.value = null; needsRecheck.value = false; load() }, { immediate: true })
watch(() => ws.jobsVersion, async () => {
  if (!recheckJob.value) {
    if (doc.value && ['queued', 'processing', 'needs_review'].includes(doc.value.status)) {
      const fresh = await documents.get(props.documentId).catch(() => null)
      if (fresh && fresh.status !== doc.value.status) load()
      else if (fresh) doc.value = fresh
    }
    return
  }
  const j = ws.jobs.find(x => x.id === recheckJob.value)
  if (j && ['succeeded', 'failed', 'partially_succeeded'].includes(j.status)) {
    recheckJob.value = null
    needsRecheck.value = false
    await loadIssues()
    notify.ok(j.status === 'succeeded' ? `Проверка готова: открытых замечаний в корпусе ${j.result?.issues_open ?? 0}` : 'Проверка завершилась с ошибкой')
  }
})

const entityTabs = computed(() => {
  if (!graph.value) return []
  return Object.keys(graph.value.entities)
    .sort((a, b) => (ENTITY[a]?.order ?? 9) - (ENTITY[b]?.order ?? 9))
    .map(t => ({ value: t, label: ENTITY[t]?.many || t, count: graph.value.entities[t].length }))
})
const openByRecord = computed(() => {
  const m = {}
  for (const i of issues.value) if (!i.stale && i.status === 'open') for (const r of i.record_ids) (m[r] ||= []).push(i)
  return m
})
const issuesFor = id => issues.value.filter(i => !i.stale && i.record_ids.includes(id))
const items = computed(() => {
  if (!graph.value || !type.value) return []
  const list = sortItems(type.value, graph.value.entities[type.value])
  return onlyIssues.value ? list.filter(it => openByRecord.value[it[ID_FIELD[type.value]]]) : list
})
const isResult = computed(() => type.value === 'solar_result' || type.value === 'rag_result')
const selectedItem = computed(() => graph.value?.entities[type.value]?.find(it => it[ID_FIELD[type.value]] === selectedId.value) || null)
function toneOf (id) {
  const list = openByRecord.value[id] || []
  if (list.some(i => i.severity === 'error')) return 'error'
  if (list.length) return 'warn'
  return 'idle'
}
const boxes = computed(() => {
  if (!graph.value || !type.value) return []
  const ids = new Set((graph.value.entities[type.value] || []).map(it => it[ID_FIELD[type.value]]))
  return graph.value.evidence.filter(e => ids.has(e.entity_id) && e.bbox).map(e => {
    const it = graph.value.entities[type.value].find(x => x[ID_FIELD[type.value]] === e.entity_id)
    return { id: e.entity_id, page: e.page, bbox: e.bbox, tone: toneOf(e.entity_id), label: pinLabel(type.value, it) }
  })
})
const activeLabel = computed(() => {
  const b = boxes.value.find(x => x.id === selectedId.value)
  return b ? `${b.label}, стр. ${b.page}` : (selectedId.value ? `${selectedId.value}: источник не найден` : '')
})
const issueCount = computed(() => issues.value.filter(i => !i.stale && i.status === 'open').length)

function select (id, updateUrl = true) {
  selectedId.value = selectedId.value === id && updateUrl ? null : id
  if (!selectedId.value) return
  const ev = evidenceOf(graph.value, id)
  if (ev) focus.value = { page: ev.page, bbox: ev.bbox, t: Date.now() }
  if (updateUrl) router.replace({ query: { ...route.query, profile: profile.value, entity: type.value, record: id, page: undefined } })
  nextTick(() => listEl.value?.querySelector(`[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
}
function onPin (id) { select(id) }
function setType (t) {
  type.value = t
  selectedId.value = null
  router.replace({ query: { ...route.query, entity: t, record: undefined } })
}
function onChanged (res) {
  graph.value = res.data
  etag.value = res.etag
  needsRecheck.value = true
  if (selectedId.value && !graph.value.entities[type.value]?.some(it => it[ID_FIELD[type.value]] === selectedId.value)) selectedId.value = null
  pub.value && publications.get(pub.value.id).then(p => { pub.value = p }).catch(() => {})
}
async function onStale () {
  notify.info('Граф изменился в другом окне: загружена свежая версия')
  await loadGraph()
}
async function recheck () {
  try {
    const r = await jobs.create(props.corpusId, { kind: 'validate', target_profiles: [profile.value], check_sources: true })
    recheckJob.value = r.job_id
    kickJobs()
  } catch (e) { notify.error(e) }
}
function edit () { form.value = { open: true, mode: 'edit', item: selectedItem.value } }
function create () { form.value = { open: true, mode: 'create', item: null } }
function onSaved (res) {
  onChanged(res)
  if (form.value.mode === 'create') {
    const ids = new Set((graph.value.entities[type.value] || []).map(it => it[ID_FIELD[type.value]]))
    const added = [...ids].find(id => !items.value.some(x => x[ID_FIELD[type.value]] === id))
    if (added) select(added)
  }
}
function switchProfile (p) {
  profile.value = p
  selectedId.value = null
  type.value = null
  router.replace({ query: { profile: p } })
  loadGraph()
}
function onActivated (res) { onChanged(res); historyOpen.value = false }

const cls = computed(() => doc.value?.classification || null)
const state = computed(() => {
  if (!doc.value) return null
  if (graph.value && graph.value.scope?.in_scope !== false) return 'graph'
  return doc.value.status
})
const topicChips = computed(() => (cls.value?.labels || []).map(l => profileTitle(LABEL_TO_PROFILE[l])))
const progress = computed(() => doc.value?.processing?.progress?.total ? doc.value.processing.progress.done / doc.value.processing.progress.total : null)
</script>

<template>
  <div class="art" :class="{ 'art--mobile': ui.mobile }">
    <header class="art__head">
      <RouterLink :to="`/corpora/${corpusId}/documents`" class="btn btn--ghost btn--sm art__back" aria-label="К документам"><ChevronLeft /><span v-if="!ui.mobile">Документы</span></RouterLink>
      <template v-if="doc">
        <b class="art__code">{{ doc.publication_code }}</b>
        <h1 class="art__title" :title="doc.title || doc.original_filename">{{ doc.title || doc.original_filename }}</h1>
        <span v-for="t in topicChips" v-show="!ui.mobile" :key="t" class="chip chip--plain">{{ t }}</span>
        <Segmented v-if="pub && Object.keys(pub.profiles).length > 1" :model-value="profile" :options="Object.keys(pub.profiles).map(p => ({ value: p, label: profileShort(p) }))" size="sm" label="Профиль" @update:model-value="switchProfile" />
        <span class="grow" />
        <button v-if="graph && pub?.profiles?.[profile]?.candidates && !ui.mobile" class="chip chip--wait art__cand" type="button" @click="historyOpen = true">Есть новая версия</button>
        <button v-if="graph && !ui.mobile" class="btn btn--sm" type="button" @click="historyOpen = true"><History />Версия {{ graph.revision_number }}</button>
      </template>
    </header>

    <div class="art__body">
      <section v-if="!ui.mobile" class="art__pdf">
        <PdfViewer v-if="doc" :document-id="doc.id" :boxes="boxes" :active-id="selectedId" :active-label="activeLabel" :focus="focus" @select="onPin" />
      </section>

      <aside class="art__panel">
        <div v-if="loading" class="art__pad"><div v-for="i in 5" :key="i" class="skeleton" style="height: 44px; margin-bottom: 8px" /></div>

        <template v-else-if="state === 'graph'">
          <div class="art__tabs" role="tablist" aria-label="Типы записей">
            <button v-for="t in entityTabs" :key="t.value" type="button" role="tab" class="art__tab" :class="{ 'is-on': t.value === type }" :aria-selected="t.value === type" @click="setType(t.value)">
              {{ t.label }}<span class="num">{{ t.count }}</span>
            </button>
          </div>
          <div class="art__tools">
            <label v-if="issueCount" class="check art__only"><input v-model="onlyIssues" type="checkbox">Только с замечаниями <span class="count count--warn">{{ issueCount }}</span></label>
            <span class="grow" />
            <button v-if="editable && !ui.mobile" class="btn btn--sm btn--ghost" type="button" @click="create"><Plus />Добавить</button>
          </div>
          <div v-if="needsRecheck" class="art__recheck">
            <p>Граф изменён. Замечания посчитаны по прежней версии.</p>
            <button class="btn btn--sm" type="button" :disabled="!!recheckJob || !editable" @click="recheck"><RefreshCw />{{ recheckJob ? 'Проверяю…' : 'Пересчитать' }}</button>
          </div>

          <ul ref="listEl" class="recs">
            <li v-for="it in items" :key="it[ID_FIELD[type]]" :data-id="it[ID_FIELD[type]]" class="rec" :class="{ 'is-on': selectedId === it[ID_FIELD[type]], [`rec--${toneOf(it[ID_FIELD[type]])}`]: true }">
              <button type="button" class="rec__row" :aria-expanded="selectedId === it[ID_FIELD[type]]" @click="select(it[ID_FIELD[type]])">
                <span class="rec__mark" aria-hidden="true" />
                <span class="rec__main">
                  <span class="rec__title">
                    <Metric v-if="isResult" :name="it.metric_name" :k="it.metric_k" />
                    <template v-else>{{ rowText(type, it, graph).title }}</template>
                    <span class="rec__id faint">{{ it[ID_FIELD[type]] }}</span>
                  </span>
                  <span class="rec__sub muted">{{ rowText(type, it, graph).sub }}</span>
                </span>
                <span v-if="isResult" class="rec__val num">{{ fmtResult(it) }}</span>
                <span v-if="isResult" class="rec__page faint">{{ evidenceOf(graph, it[ID_FIELD[type]]) ? `стр. ${evidenceOf(graph, it[ID_FIELD[type]]).page}` : 'нет источника' }}</span>
              </button>
              <div v-if="selectedId === it[ID_FIELD[type]] && !ui.mobile" class="rec__detail">
                <RecordDetail :type="type" :item="it" :graph="graph" :etag="etag" :profile="profile" :publication-id="pub.id" :document-id="doc.id" :issues="issuesFor(it[ID_FIELD[type]])" :editable="editable" @edit="edit" @changed="onChanged" @stale="onStale" @issues-changed="loadIssues" />
              </div>
            </li>
            <li v-if="!items.length" class="art__pad muted">{{ onlyIssues ? 'У записей этого типа нет открытых замечаний.' : 'Записей этого типа нет.' }}</li>
          </ul>
        </template>

        <div v-else-if="doc" class="art__state">
          <template v-if="state === 'needs_review'">
            <CircleAlert class="art__icon art__icon--warn" />
            <h2>Тема статьи не определена уверенно</h2>
            <p>{{ cls?.note }}</p>
            <p class="muted">Оценка модели: солнечные элементы {{ fmtNum(cls?.scores?.solar, 2) }}, RAG {{ fmtNum(cls?.scores?.rag, 2) }}. Обработка продолжится после решения.</p>
            <button v-if="editable" class="btn btn--primary" type="button" @click="decideOpen = true">Решить тему</button>
          </template>
          <template v-else-if="state === 'processing' || state === 'queued'">
            <Hourglass class="art__icon" />
            <h2>{{ state === 'queued' ? 'Статья в очереди' : 'Идёт обработка' }}</h2>
            <p v-if="doc.processing">{{ STAGE[doc.processing.stage] }}<template v-if="doc.processing.progress?.total">: {{ doc.processing.progress.done }} из {{ doc.processing.progress.total }} стр.</template></p>
            <Progress :value="progress" style="max-width: 280px; width: 100%" />
          </template>
          <template v-else-if="state === 'outside'">
            <Ban class="art__icon" />
            <h2>Статья вне тем корпуса</h2>
            <p>В выгрузку попадёт только библиография с пометкой not_target_domain.</p>
            <blockquote v-if="cls?.labels && pub?.classification?.evidence?.[0]" class="quote">{{ pub.classification.evidence[0].fragment }}</blockquote>
          </template>
          <template v-else-if="state === 'excluded'">
            <Ban class="art__icon" />
            <h2>Вне рамок профиля {{ profileShort(profile) }}</h2>
            <p>{{ cls?.note || graph?.scope?.exclusion_reason }}</p>
            <p class="muted">Записи не извлекаются. В publications.csv статья попадёт с in_scope = false и причиной.</p>
          </template>
          <template v-else-if="state === 'unreadable'">
            <FileX class="art__icon art__icon--bad" />
            <h2>PDF не читается</h2>
            <p>{{ cls?.note || 'Файл повреждён или защищён паролем.' }}</p>
            <p class="muted">Загрузите исправный файл под тем же кодом статьи или отметьте пропуск в выгрузке.</p>
          </template>
          <template v-else-if="state === 'blocked'">
            <CircleAlert class="art__icon art__icon--warn" />
            <h2>Модель не подключена</h2>
            <p>{{ doc.processing?.error?.message }}.</p>
            <p class="muted">Файл и текст страниц проверены. Записи появятся после подключения модели на сервере.</p>
          </template>
          <template v-else>
            <Hourglass class="art__icon" />
            <h2>{{ DOC_STATUS[state]?.text || 'Статья ещё не обработана' }}</h2>
            <p class="muted">Запустите обработку на странице документов.</p>
          </template>
        </div>
      </aside>
    </div>

    <Drawer v-if="ui.mobile" :open="!!selectedItem" :title="selectedItem ? (isResult ? `${selectedItem.metric_name} ${fmtResult(selectedItem)}` : selectedId) : ''" @close="selectedId = null">
      <RecordDetail v-if="selectedItem" :type="type" :item="selectedItem" :graph="graph" :etag="etag" :profile="profile" :publication-id="pub.id" :document-id="doc.id" :issues="issuesFor(selectedId)" :editable="editable" mobile @changed="onChanged" @stale="onStale" @issues-changed="loadIssues" />
    </Drawer>

    <EntityForm :open="form.open" :mode="form.mode" :type="type" :item="form.item" :profile="profile" :publication-id="pub?.id" :graph="graph" :etag="etag" @close="form.open = false" @saved="onSaved" @stale="onStale" />
    <HistoryDrawer v-if="pub && profile" :open="historyOpen" :publication-id="pub.id" :profile="profile" :etag="etag" :editable="editable" @close="historyOpen = false" @activated="onActivated" />
    <ClassificationDialog v-if="doc" :open="decideOpen" :document-id="doc.id" :code="doc.publication_code" @close="decideOpen = false" @done="load" />
  </div>
</template>

<style>
.art { display: flex; flex-direction: column; height: calc(100vh - var(--header-h)); min-height: 520px; }
.art__head { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 8px var(--s-4) 8px var(--s-3); border-bottom: 1px solid var(--line); background: var(--surface); }
.art__back { flex: none; }
.art__code { font-size: var(--fs-lg); flex: none; }
.art__title { min-width: 0; flex: 0 1 auto; font-size: var(--fs-md); font-weight: 400; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art__cand { border: 0; cursor: pointer; }
.art__body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) clamp(380px, 34vw, 500px); }
.art__pdf { min-width: 0; min-height: 0; border-right: 1px solid var(--line); }
.art__panel { min-height: 0; overflow: auto; background: var(--surface); }
.art__pad { padding: var(--s-4); }
.art__tabs { position: sticky; top: 0; z-index: 2; display: flex; gap: 2px; padding: 8px 10px 0; overflow-x: auto; background: var(--surface); border-bottom: 1px solid var(--line); scrollbar-width: none; }
.art__tab { position: relative; display: flex; align-items: center; gap: 6px; height: 36px; padding: 0 10px; border: 0; background: none; color: var(--muted); font-size: var(--fs-sm); font-weight: 500; white-space: nowrap; cursor: pointer; }
.art__tab .num { color: var(--faint); }
.art__tab:hover { color: var(--ink); }
.art__tab.is-on { color: var(--ink); }
.art__tab.is-on::after { content: ""; position: absolute; left: 8px; right: 8px; bottom: -1px; height: 2px; border-radius: 2px 2px 0 0; background: var(--accent); }
.art__tools { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 4px 12px 4px 16px; }
.art__only { font-size: var(--fs-sm); }
.art__recheck { display: flex; align-items: center; gap: 10px; margin: 0 12px 8px; padding: 10px 12px; border-radius: var(--r-md); background: var(--info-fill); color: var(--info); font-size: var(--fs-sm); }
.art__recheck p { flex: 1; }
.recs { padding: 0 8px 24px; }
.rec { border-radius: var(--r-md); }
.rec + .rec { margin-top: 1px; }
.rec__row { position: relative; display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; grid-template-rows: auto auto; column-gap: 10px; width: 100%; padding: 9px 10px 9px 8px; border: 0; border-radius: var(--r-md); background: none; text-align: left; cursor: pointer; }
.rec__row:hover { background: var(--surface-hover); }
.rec__mark { grid-row: 1 / 3; align-self: stretch; width: 3px; margin-left: 2px; border-radius: 2px; background: transparent; }
.rec--warn .rec__mark { background: var(--warn-line); }
.rec--error .rec__mark { background: var(--danger-line); }
.rec.is-on .rec__mark { background: var(--accent); }
.rec__main { grid-column: 2; grid-row: 1 / 3; min-width: 0; }
.rec__title { display: flex; align-items: baseline; gap: 8px; font-weight: 500; }
.rec__id { font-size: var(--fs-xs); font-weight: 400; }
.rec__sub { display: block; font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rec__val { grid-column: 3; grid-row: 1; text-align: right; font-weight: 500; white-space: nowrap; }
.rec__page { grid-column: 3; grid-row: 2; text-align: right; font-size: var(--fs-xs); white-space: nowrap; }
.rec--error .rec__page { color: var(--danger); }
.rec.is-on > .rec__row { background: var(--accent-soft); }
.rec__detail { padding: 8px 12px 14px 22px; border-bottom: 1px solid var(--line); margin-bottom: 6px; }
.art__state { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; padding: var(--s-8) var(--s-6); max-width: 460px; }
.art__state h2 { font-size: var(--fs-lg); }
.art__state .quote { margin-top: 6px; }
.art__icon { width: 26px; height: 26px; color: var(--muted); }
.art__icon--warn { color: var(--warn); }
.art__icon--bad { color: var(--danger); }
.art--mobile { height: auto; min-height: calc(100vh - var(--header-h)); }
.art--mobile .art__head { flex-wrap: wrap; padding: 8px 12px; }
.art--mobile .art__title { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; flex-basis: 100%; order: 5; }
.art--mobile .art__body { display: block; }
.art--mobile .art__panel { overflow: visible; padding-bottom: calc(var(--tabbar-h) + 16px); background: var(--bg); }
.art--mobile .art__tabs { top: var(--header-h); background: var(--bg); }
.art--mobile .rec__row { padding: 12px 10px 12px 8px; }
@media (max-width: 1100px) and (min-width: 720px) {
  .art__body { grid-template-columns: minmax(0, 1fr) 380px; }
}
</style>
