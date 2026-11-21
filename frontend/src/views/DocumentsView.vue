<!-- Назначение файла: документы корпуса: статус каждой статьи, загрузка PDF, запуск обработки и определения темы,
     полоса текущего задания. На телефоне список карточек без загрузки и запуска. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, Play, ChevronDown, Tags } from '@lucide/vue'
import Chip from '../components/ui/Chip.vue'
import Menu from '../components/ui/Menu.vue'
import JobBanner from '../components/app/JobBanner.vue'
import UploadDialog from '../components/app/UploadDialog.vue'
import { documents, jobs } from '../api/index.js'
import { ws, kickJobs } from '../stores/workspace.js'
import { canEdit } from '../stores/session.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { askReason } from '../stores/dialogs.js'
import { DOC_STATUS, STAGE, profileShort, LABEL_TO_PROFILE } from '../lib/labels.js'
import { fmtDate, fmtNum, countText } from '../lib/format.js'

const router = useRouter()
const list = ref([])
const loading = ref(true)
const filter = ref('all')
const selected = ref(new Set())
const uploadOpen = ref(false)
const editable = computed(() => canEdit(ws.corpus))
const retrying = ref(new Set())

async function retryBlocked (doc) {
  if (!doc.processing?.job_id || retrying.value.has(doc.id)) return
  retrying.value.add(doc.id)
  try {
    await jobs.retry(doc.processing.job_id)
    notify.ok('Повтор обработки запущен')
    kickJobs()
    await load()
  } catch (e) { notify.error(e) } finally { retrying.value.delete(doc.id) }
}

async function load () {
  try {
    const res = await documents.list(ws.corpus.id)
    list.value = res.items
    for (const id of [...selected.value]) if (!res.items.some(d => d.id === id)) selected.value.delete(id)
  } catch (e) { notify.error(e) } finally { loading.value = false }
}
onMounted(load)
let t = null
watch(() => ws.jobsVersion, () => { clearTimeout(t); t = setTimeout(load, 150) })

const GROUPS = {
  all: { label: 'Все', test: () => true },
  ready: { label: 'Готово', test: d => d.status === 'ready' },
  wait: { label: 'Ждут решения', test: d => d.status === 'needs_review' },
  run: { label: 'В работе', test: d => ['queued', 'processing'].includes(d.status) },
  other: { label: 'Без записей', test: d => ['outside', 'excluded', 'unreadable', 'failed', 'blocked', 'uploaded'].includes(d.status) }
}
const counts = computed(() => Object.fromEntries(Object.entries(GROUPS).map(([k, g]) => [k, list.value.filter(g.test).length])))
const shown = computed(() => list.value.filter(GROUPS[filter.value].test))
const waitingDocs = computed(() => list.value.filter(d => d.status === 'needs_review'))
const allChecked = computed(() => shown.value.length > 0 && shown.value.every(d => selected.value.has(d.id)))
function toggleAll () {
  if (allChecked.value) shown.value.forEach(d => selected.value.delete(d.id))
  else shown.value.forEach(d => selected.value.add(d.id))
}
function toggle (id) { selected.value.has(id) ? selected.value.delete(id) : selected.value.add(id) }
function open (d) { router.push({ name: 'article', params: { corpusId: ws.corpus.id, documentId: d.id } }) }

async function run (kind) {
  const ids = [...selected.value]
  const n = ids.length || list.value.length
  const what = kind === 'process' ? 'Обработать' : 'Определить тему для'
  const ok = await askReason({
    title: `${what} ${countText(n, ['статью', 'статьи', 'статей'])}?`,
    text: kind === 'process'
      ? 'Задание пройдёт этапы: файл, текст, распознавание, тема, извлечение, связи, сверка с источником. Ручные правки не затираются: новая версия придёт кандидатом.'
      : 'Модель определит тему каждой статьи. Неуверенные решения попадут в очередь проверки.',
    confirm: kind === 'process' ? 'Запустить обработку' : 'Запустить',
    withReason: false
  })
  if (!ok) return
  try {
    await jobs.create(ws.corpus.id, ids.length ? { kind, document_ids: ids } : { kind, all_documents: true })
    selected.value.clear()
    notify.ok(kind === 'process' ? 'Обработка запущена' : 'Определение темы запущено')
    kickJobs()
  } catch (e) {
    notify.error(e)
  }
}
const topic = d => (d.classification?.labels || []).map(l => profileShort(LABEL_TO_PROFILE[l]))
</script>

<template>
  <div class="page docs">
    <div class="page__head">
      <h1 class="page__title">Документы<span class="count">{{ list.length }}</span></h1>
      <span class="grow" />
      <template v-if="editable && !ui.mobile">
        <Menu width="260px">
          <template #trigger="{ toggle: t }">
            <button class="btn" type="button" @click="t">Ещё<ChevronDown /></button>
          </template>
          <button class="menu__item" type="button" @click="run('classify')"><Tags />Определить тему{{ selected.size ? ` (${selected.size})` : '' }}</button>
        </Menu>
        <button class="btn" type="button" :disabled="!list.length" @click="run('process')"><Play />{{ selected.size ? `Обработать выбранные (${selected.size})` : 'Обработать все' }}</button>
        <button class="btn btn--primary" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
      </template>
    </div>

    <JobBanner :waiting-docs="waitingDocs" @changed="load" />

    <div class="docs__filters" role="tablist" aria-label="Фильтр по статусу">
      <button v-for="(g, k) in GROUPS" v-show="k === 'all' || counts[k]" :key="k" type="button" role="tab" class="docs__filter" :class="{ 'is-on': filter === k }" :aria-selected="filter === k" @click="filter = k">
        {{ g.label }}<span class="num">{{ counts[k] }}</span>
      </button>
    </div>

    <div v-if="loading" class="panel"><div v-for="i in 6" :key="i" class="skeleton" style="height: 28px; margin: 14px 16px" /></div>
    <div v-else-if="!list.length" class="panel empty">
      <h3>В корпусе пока нет статей</h3>
      <p>Загрузите PDF: код статьи возьмётся из имени файла, дубликаты отсеются по коду и хешу.</p>
      <button v-if="editable && !ui.mobile" class="btn btn--primary" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
    </div>

    <ul v-else-if="ui.mobile" class="doccards">
      <li v-for="d in shown" :key="d.id">
        <button type="button" class="doccard" @click="open(d)">
          <span class="doccard__top"><b>{{ d.publication_code }}</b><Chip :tone="DOC_STATUS[d.status]?.tone" :text="DOC_STATUS[d.status]?.text || d.status" /></span>
          <span class="doccard__title">{{ d.title || d.original_filename }}</span>
          <span v-if="d.status_hint" class="muted">{{ d.status_hint }}</span>
          <span class="doccard__meta muted">
            <template v-if="d.status === 'processing'">{{ STAGE[d.processing?.stage] }}</template>
            <template v-else-if="d.records">{{ countText(d.records, ['запись', 'записи', 'записей']) }}</template>
            <template v-else>{{ topic(d).join(', ') || 'тема не определена' }}</template>
            <span v-if="d.issues_open" class="doccard__warn">{{ countText(d.issues_open, ['замечание', 'замечания', 'замечаний']) }}</span>
          </span>
        </button>
      </li>
    </ul>

    <div v-else class="panel docs__table">
      <table class="table">
        <thead>
          <tr>
            <th v-if="editable" class="t-check"><input type="checkbox" class="cb" :checked="allChecked" aria-label="Выбрать все" @change="toggleAll"></th>
            <th>Код</th>
            <th>Статья</th>
            <th>Тема</th>
            <th>Статус</th>
            <th class="t-num">Записи</th>
            <th class="t-num">Замечания</th>
            <th>Загружен</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in shown" :key="d.id" class="is-link" :class="{ 'is-selected': selected.has(d.id) }" @click="open(d)">
            <td v-if="editable" class="t-check" @click.stop><input type="checkbox" class="cb" :checked="selected.has(d.id)" :aria-label="`Выбрать ${d.publication_code}`" @change="toggle(d.id)"></td>
            <td class="nowrap"><b>{{ d.publication_code }}</b></td>
            <td class="docs__title">
              <span class="ellipsis">{{ d.title || d.original_filename }}</span>
              <span class="faint docs__file">{{ d.original_filename }}<template v-if="d.page_count">, {{ d.page_count }} стр.</template><template v-if="d.year">, {{ d.year }}</template></span>
            </td>
            <td class="nowrap">
              <span v-if="topic(d).length" class="docs__topics"><span v-for="t2 in topic(d)" :key="t2" class="chip chip--plain">{{ t2 }}</span></span>
              <span v-else class="faint">{{ d.classification?.outcome === 'outside' ? 'вне тем' : '–' }}</span>
            </td>
            <td class="docs__status">
              <Chip :tone="DOC_STATUS[d.status]?.tone" :text="DOC_STATUS[d.status]?.text || d.status" />
              <span v-if="d.status_hint" class="faint docs__stage" style="max-width: 250px">{{ d.status_hint }}</span>
              <button v-if="d.status === 'blocked' && editable" class="btn btn--sm" type="button" :disabled="retrying.has(d.id)" @click.stop="retryBlocked(d)">Повторить задание</button>
              <span v-if="d.status === 'processing' && d.processing" class="faint docs__stage">{{ STAGE[d.processing.stage] }}<template v-if="d.processing.progress?.total && ['text', 'extract'].includes(d.processing.stage)">, {{ d.processing.progress.done }}/{{ d.processing.progress.total }}</template></span>
            </td>
            <td class="t-num">{{ d.records ? fmtNum(d.records, 0) : '–' }}</td>
            <td class="t-num"><span v-if="d.issues_open" class="count count--warn">{{ d.issues_open }}</span><span v-else class="faint">–</span></td>
            <td class="nowrap muted">{{ fmtDate(d.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!shown.length" class="empty">В этом фильтре статей нет.</p>
    </div>

    <UploadDialog :open="uploadOpen" :corpus-id="ws.corpus.id" @close="uploadOpen = false" @uploaded="load" />
  </div>
</template>

<style>
.docs__filters { display: flex; gap: 4px; margin-bottom: var(--s-3); flex-wrap: wrap; }
.docs__filter { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px; border: 1px solid transparent; border-radius: 15px; background: none; color: var(--muted); font-size: var(--fs-sm); font-weight: 500; cursor: pointer; }
.docs__filter .num { color: var(--faint); }
.docs__filter:hover { color: var(--ink); background: var(--surface-hover); }
.docs__filter.is-on { color: var(--ink); background: var(--surface); border-color: var(--line-strong); }
.docs__table { overflow: auto; }
.docs__title { max-width: 0; width: 46%; }
.docs__title .ellipsis { display: block; }
.docs__file { display: block; font-size: var(--fs-sm); }
.docs__topics { display: inline-flex; gap: 4px; }
.docs__status { white-space: nowrap; }
.docs__stage { display: block; margin-top: 3px; font-size: var(--fs-xs); white-space: normal; }
.cb { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); cursor: pointer; vertical-align: middle; }
@media (max-width: 719px) { .docs__filters { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin-right: -16px; } .docs__filter { flex: none; } }
.doccards { display: flex; flex-direction: column; gap: 8px; }
.doccard { display: flex; flex-direction: column; gap: 6px; width: 100%; padding: 14px 16px; border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); text-align: left; cursor: pointer; }
.doccard__top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.doccard__title { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35; }
.doccard__meta { display: flex; gap: 12px; font-size: var(--fs-sm); }
.doccard__warn { color: var(--warn); }
</style>
