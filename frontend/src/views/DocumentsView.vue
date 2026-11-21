<!-- Назначение файла: документы корпуса: статус каждой статьи, загрузка PDF, запуск обработки и определения темы,
     полоса текущего задания. На телефоне список карточек без загрузки и запуска. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, Trash2 } from '@lucide/vue'
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
// тема словом: цветные плитки ничего не добавляли к смыслу
const topicWord = d => { const l = d.classification?.labels || []; return l.includes('solar') && l.includes('rag') ? 'Солнечные и RAG' : l.includes('solar') ? 'Солнечные' : l.includes('rag') ? 'RAG' : '' }
</script>

<template>
  <div class="page docs">
    <div class="page__head">
      <h1 class="page__title">Документы</h1>
      <div class="tabs docs__filters" role="tablist" aria-label="Фильтр по статусу">
        <button v-for="(g, k) in GROUPS" v-show="k === 'all' || counts[k]" :key="k" type="button" role="tab" class="tab" :class="{ 'is-on': filter === k }" :aria-selected="filter === k" @click="filter = k">
          {{ g.label }}<span class="tab__n">{{ counts[k] }}</span>
        </button>
      </div>
      <span class="grow" />
      <template v-if="editable && !ui.mobile">
        <template v-if="selected.size">
          <span class="docs__picked">Выбрано {{ selected.size }}</span>
          <button class="btn btn--ghost" type="button" @click="selected.clear()">Снять выбор</button>
          <button class="btn" type="button" @click="run('classify')">Определить тему</button>
          <button class="btn btn--primary" type="button" @click="run('process')">Обработать</button>
        </template>
        <template v-else>
          <button class="btn btn--ghost" type="button" :disabled="!list.length" @click="run('process')">Обработать все</button>
          <button class="btn btn--accent" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
        </template>
      </template>
    </div>

    <JobBanner :waiting-docs="waitingDocs" @changed="load" />

    <div v-if="loading" class="docs__skel"><span v-for="i in 6" :key="i" class="skeleton" style="height: 18px; margin: 14px 0" /></div>
    <div v-else-if="!list.length" class="empty">
      <h3>В корпусе пока нет статей</h3>
      <p>Загрузите PDF. Код статьи возьмётся из имени файла, повторы отсеются.</p>
      <button v-if="editable && !ui.mobile" class="btn btn--accent" type="button" @click="uploadOpen = true"><Upload />Загрузить PDF</button>
    </div>

    <table v-else-if="!ui.mobile" class="table docs__table">
      <thead>
        <tr>
          <th class="t-check"><input v-if="editable" type="checkbox" class="cb" :checked="allChecked" aria-label="Выбрать все" @change="toggleAll"></th>
          <th>Код</th>
          <th>Название</th>
          <th>Тема</th>
          <th>Статус</th>
          <th class="t-num">Записи</th>
          <th class="t-num">Замечания</th>
          <th v-if="deletable" class="t-act"><span class="visually-hidden">Удаление</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in shown" :key="d.id" class="is-link" :class="{ 'is-selected': selected.has(d.id) }" @click="open(d)">
          <td class="t-check" @click.stop><input v-if="editable" type="checkbox" class="cb" :checked="selected.has(d.id)" :aria-label="`Выбрать ${d.publication_code}`" @change="toggle(d.id)"></td>
          <td class="docs__code">{{ d.publication_code }}</td>
          <td class="docs__name">
            <span class="docs__title">{{ d.title || d.original_filename }}</span>
            <span v-if="d.status_hint" class="docs__hint">{{ d.status_hint }}</span>
          </td>
          <td class="docs__topic">{{ topicWord(d) }}</td>
          <td class="docs__st">
            <Chip :tone="DOC_STATUS[d.status]?.tone" :text="DOC_STATUS[d.status]?.text || d.status" />
            <span v-if="d.status === 'processing' && d.processing" class="docs__stage">{{ STAGE[d.processing.stage] }}<template v-if="d.processing.progress?.total && ['text', 'extract'].includes(d.processing.stage)">, {{ d.processing.progress.done }} из {{ d.processing.progress.total }}</template></span>
            <button v-if="d.status === 'blocked' && editable" class="btn btn--sm docs__retry" type="button" :disabled="retrying.has(d.id)" @click.stop="retryBlocked(d)">Повторить задание</button>
          </td>
          <td class="t-num">{{ d.records ? fmtNum(d.records, 0) : '' }}</td>
          <td class="t-num"><span v-if="d.issues_open" class="count count--warn">{{ d.issues_open }}</span></td>
          <td v-if="deletable" class="t-act" @click.stop><button class="btn btn--ghost btn--icon btn--sm row-del" type="button" :aria-label="`Удалить статью ${d.publication_code}`" :title="`Удалить статью ${d.publication_code}`" :disabled="deleting.has(d.id)" @click="remove(d)"><Trash2 /></button></td>
        </tr>
      </tbody>
    </table>

    <ul v-else class="docs__list">
      <li v-for="d in shown" :key="d.id">
        <button type="button" class="docs__row" @click="open(d)">
          <span class="docs__line"><b>{{ d.publication_code }}</b><Chip :tone="DOC_STATUS[d.status]?.tone" :text="DOC_STATUS[d.status]?.text || d.status" /></span>
          <span class="docs__title">{{ d.title || d.original_filename }}</span>
          <span v-if="d.status_hint" class="docs__hint">{{ d.status_hint }}</span>
        </button>
      </li>
    </ul>
    <p v-if="!loading && list.length && !shown.length" class="empty">В этом фильтре статей нет.</p>

    <UploadDialog :open="uploadOpen" :corpus-id="ws.corpus.id" @close="uploadOpen = false" @uploaded="load" />
  </div>
</template>

<style>
.docs__filters { margin-left: 4px; }
.docs__picked { color: var(--pencil); }
.docs__table td { vertical-align: top; padding-top: 12px; }
.docs__code { width: 64px; font-weight: 600; white-space: nowrap; }
.docs__name { max-width: 0; width: 100%; }
.docs__title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.docs__hint { display: block; margin-top: 2px; font-size: 13px; line-height: 18px; color: var(--pencil); white-space: normal; }
.docs__topic { width: 150px; color: var(--pencil); white-space: nowrap; }
.docs__st { width: 190px; }
.docs__st .chip { display: flex; }
.docs__stage { display: block; margin-top: 2px; font-size: 13px; color: var(--pencil); }
.docs__retry { margin-top: 8px; }
.docs__table .t-num { width: 96px; }
.docs__table td.t-act { padding-top: 8px; }
.docs__list { box-shadow: inset 0 1.5px 0 var(--rule-strong), inset 0 -1.5px 0 var(--rule-strong); }
.docs__list li + li { box-shadow: inset 0 1px 0 var(--rule); }
.docs__row { display: flex; flex-direction: column; gap: 3px; width: 100%; padding: 14px 0; border: 0; background: none; text-align: left; }
.docs__line { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.docs__line b { font-weight: 600; }
.docs__row .docs__title { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
@media (max-width: 719px) {
  .page__head .docs__filters { order: 5; flex-basis: 100%; margin: 0; }
}
</style>
