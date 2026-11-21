<!-- Назначение файла: документы корпуса: статус каждой статьи, загрузка PDF, запуск обработки и определения темы,
     полоса текущего задания. На телефоне список карточек без загрузки и запуска. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, Play, Tags, RotateCcw, Trash2 } from '@lucide/vue'
import Chip from '../components/ui/Chip.vue'
import JobBanner from '../components/app/JobBanner.vue'
import UploadDialog from '../components/app/UploadDialog.vue'
import { documents, jobs } from '../api/index.js'
import { ws, kickJobs, refreshCorpus } from '../stores/workspace.js'
import { canEdit, canManage } from '../stores/session.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { askReason } from '../stores/dialogs.js'
import { DOC_STATUS, STAGE } from '../lib/labels.js'
import { fmtNum, countText } from '../lib/format.js'

const router = useRouter()
const list = ref([])
const loading = ref(true)
const filter = ref('all')
const selected = ref(new Set())
const uploadOpen = ref(false)
const editable = computed(() => canEdit(ws.corpus))
const retrying = ref(new Set())
const deletable = computed(() => canManage(ws.corpus))
const deleting = ref(new Set())
async function remove (doc) {
  const accepted = await askReason({ title: `Удалить статью ${doc.publication_code}?`, text: 'Будут удалены PDF, извлечённые данные и история статьи. Выгрузки, содержащие эту статью, также станут недоступны. Это действие нельзя отменить.', confirm: 'Удалить статью', tone: 'danger', withReason: false })
  if (!accepted) return
  deleting.value.add(doc.id)
  try {
    await documents.remove(doc.id)
    selected.value.delete(doc.id)
    await Promise.all([load(), refreshCorpus()])
    kickJobs(); notify.ok('Статья удалена')
  } catch (e) { notify.error(e) } finally { deleting.value.delete(doc.id) }
}

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
  paused: { label: 'На паузе', test: d => d.status === 'paused' },
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
// метка темы в плитке строки, как в окне продукта на лендинге: S солнечные элементы, R RAG
const tag = d => { const l = d.classification?.labels || []; return l.includes('solar') && l.includes('rag') ? 'SR' : l.includes('solar') ? 'S' : l.includes('rag') ? 'R' : '–' }
const tone = d => { const l = d.classification?.labels || []; return l.includes('solar') ? 2 : l.includes('rag') ? 4 : 0 }
</script>

<template>
  <div class="page docs">
    <div class="page__head">
      <h1 class="page__title">Документы</h1>
      <div class="docs__filters" role="tablist" aria-label="Фильтр по статусу">
        <button v-for="(g, k) in GROUPS" v-show="k === 'all' || counts[k]" :key="k" type="button" role="tab" class="docs__filter" :class="{ 'is-on': filter === k }" :aria-selected="filter === k" @click="filter = k">
          {{ g.label }}<span class="num">{{ counts[k] }}</span>
        </button>
      </div>
      <span class="grow" />
      <template v-if="editable && !ui.mobile">
        <template v-if="selected.size">
          <button class="btn btn--ghost" type="button" @click="selected.clear()">Снять выбор</button>
          <button class="btn" type="button" @click="run('classify')"><Tags />Определить тему</button>
          <button class="btn btn--primary" type="button" @click="run('process')"><Play />Обработать выбранные ({{ selected.size }})</button>
        </template>
        <template v-else>
          <button class="btn btn--ghost" type="button" :disabled="!list.length" @click="run('process')"><Play />Обработать все</button>
          <button class="btn btn--accent" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
        </template>
      </template>
    </div>

    <JobBanner :waiting-docs="waitingDocs" @changed="load" />

    <div v-if="loading" class="panel docs__list"><span v-for="i in 6" :key="i" class="skeleton" style="height: 20px; margin: 12px 16px" /></div>
    <div v-else-if="!list.length" class="panel empty">
      <h3>В корпусе пока нет статей</h3>
      <p>Загрузите PDF: код статьи возьмётся из имени файла, дубликаты отсеются по коду и хешу.</p>
      <button v-if="editable && !ui.mobile" class="btn btn--accent" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
    </div>

    <div v-else class="panel docs__list" :class="{ 'is-picking': selected.size }">
      <div v-if="!ui.mobile" class="docs__cols" aria-hidden="true">
        <span><input v-if="editable" type="checkbox" class="cb docs__all" :checked="allChecked" aria-label="Выбрать все" @change="toggleAll"></span>
        <span>Статья</span><span>Название</span><span>Статус</span><span class="t-r">Записи</span><span class="t-r">Замеч.</span><span />
      </div>
      <ul>
        <li v-for="d in shown" :key="d.id" class="docs__row" :class="{ 'is-sel': selected.has(d.id) }" @click="open(d)">
          <span class="docs__pick" @click.stop>
            <span class="ui-avatar" :data-tone="tone(d)" aria-hidden="true">{{ tag(d) }}</span>
            <input v-if="editable && !ui.mobile" type="checkbox" class="cb" :checked="selected.has(d.id)" :aria-label="`Выбрать ${d.publication_code}`" @change="toggle(d.id)">
          </span>
          <span class="docs__who">{{ d.publication_code }}</span>
          <span class="docs__sub">
            <span class="docs__title">{{ d.title || d.original_filename }}</span>
            <span v-if="d.status_hint" class="docs__hint">{{ d.status_hint }}</span>
          </span>
          <span class="docs__st">
            <Chip :tone="DOC_STATUS[d.status]?.tone" :text="DOC_STATUS[d.status]?.text || d.status" />
            <span v-if="d.status === 'processing' && d.processing" class="docs__stage">{{ STAGE[d.processing.stage] }}<template v-if="d.processing.progress?.total && ['text', 'extract'].includes(d.processing.stage)">, {{ d.processing.progress.done }}/{{ d.processing.progress.total }}</template></span>
            <button v-if="d.status === 'blocked' && editable && !ui.mobile" class="btn btn--sm" type="button" :disabled="retrying.has(d.id)" @click.stop="retryBlocked(d)"><RotateCcw />Повторить задание</button>
          </span>
          <span class="docs__n num">{{ d.records ? fmtNum(d.records, 0) : '' }}</span>
          <span class="docs__n"><span v-if="d.issues_open" class="count count--warn">{{ d.issues_open }}</span></span>
          <button v-if="deletable" class="btn btn--ghost btn--icon docs__delete" type="button" :aria-label="`Удалить статью ${d.publication_code}`" :disabled="deleting.has(d.id)" @click.stop="remove(d)"><Trash2 /></button>
        </li>
      </ul>
      <p v-if="!shown.length" class="empty">В этом фильтре статей нет.</p>
    </div>

    <UploadDialog :open="uploadOpen" :corpus-id="ws.corpus.id" @close="uploadOpen = false" @uploaded="load" />
  </div>
</template>

<style>
.docs__filters { display: flex; gap: 4px; flex-wrap: wrap; margin-left: 8px; }
.docs__filter { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border: 0; border-radius: 99px; background: none; color: var(--u-muted); font-size: 13px; transition: background-color 160ms var(--u-ease), color 160ms var(--u-ease); }
.docs__filter .num { color: var(--u-soft); }
.docs__filter:hover { color: var(--u-ink); background: var(--u-fill); }
.docs__filter.is-on { color: var(--u-ink); background: var(--u-fill-2); font-weight: 500; }
.docs__filter.is-on .num { color: var(--u-muted); }
.docs__list { overflow: hidden; }
.docs__cols, .docs__row { display: grid; grid-template-columns: 28px 56px minmax(0, 1fr) 176px 56px 56px 32px; align-items: center; gap: 0 12px; padding: 0 16px; }
.docs__cols { height: 34px; color: var(--u-soft); box-shadow: inset 0 -1px 0 var(--u-line); }
.docs__cols .t-r { text-align: right; }
.docs__row { min-height: 44px; padding-top: 6px; padding-bottom: 6px; cursor: pointer; transition: background-color 160ms var(--u-ease); }
.docs__row + .docs__row { box-shadow: inset 0 1px 0 var(--u-line); }
.docs__row:hover { background: color-mix(in oklab, var(--u-ink) 3%, var(--u-bg)); }
.docs__row.is-sel { background: var(--u-tint); }
.docs__pick { position: relative; display: grid; place-items: center; width: 24px; height: 24px; }
.docs__pick .ui-avatar { font-size: 11px; letter-spacing: 0; }
.docs__pick .cb { position: absolute; inset: 4px; opacity: 0; }
.docs__row:hover .docs__pick .cb, .docs__list.is-picking .docs__pick .cb { opacity: 1; }
.docs__row:hover .docs__pick .ui-avatar, .docs__list.is-picking .docs__pick .ui-avatar { opacity: 0; }
.docs__all { margin-left: 4px; }
.docs__who { font-weight: 500; white-space: nowrap; }
.docs__sub { display: flex; flex-direction: column; min-width: 0; }
.docs__title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.docs__hint { color: var(--u-muted); font-size: 12px; line-height: 16px; }
.docs__st { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; min-width: 0; }
.docs__stage { font-size: 12px; line-height: 16px; color: var(--u-soft); }
.docs__n { text-align: right; color: var(--u-text-2); }
@media (max-width: 719px) {
  .page__head .docs__filters { order: 5; flex-basis: 100%; margin: 4px 0 0; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
  .docs__filter { flex: none; }
  .docs__row { grid-template-columns: 24px minmax(0, 1fr) auto 32px; grid-template-rows: auto auto; gap: 2px 10px; padding: 10px 14px; }
  .docs__pick { grid-row: 1 / 3; }
  .docs__who { grid-column: 2; grid-row: 1; }
  .docs__sub { grid-column: 2 / 5; grid-row: 2; }
  .docs__delete { grid-column: 4; grid-row: 1; }
  .docs__st { grid-column: 3; grid-row: 1; align-items: flex-end; }
  .docs__n, .docs__stage { display: none; }
}
</style>
