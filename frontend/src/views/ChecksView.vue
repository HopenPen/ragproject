<!-- Назначение файла: проверки корпуса: замечания научных правил с решением редактора и единая очередь
     (тема статьи, рамки профиля, новые версии, сомнительные источники, открытые замечания).
     Запуск проверки создаёт задание validate, замечания пересчитываются по активным версиям. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ShieldCheck } from '@lucide/vue'
import Segmented from '../components/ui/Segmented.vue'
import Chip from '../components/ui/Chip.vue'
import IssueCard from '../components/app/IssueCard.vue'
import ClassificationDialog from '../components/app/ClassificationDialog.vue'
import { catalog, jobs } from '../api/index.js'
import { ws, kickJobs, refreshCorpus } from '../stores/workspace.js'
import { canEdit } from '../stores/session.js'
import { ui } from '../stores/ui.js'
import { notify } from '../stores/toasts.js'
import { REVIEW_KIND, TERMINAL, profileShort } from '../lib/labels.js'
import { fmtDate } from '../lib/format.js'

const router = useRouter()
const tab = ref('issues')
const status = ref('open')
const profile = ref('')
const issues = ref([])
const skipped = ref([])
const queue = ref([])
const loading = ref(true)
const decide = ref(null)
const runningJob = ref(null)
const editable = computed(() => canEdit(ws.corpus))

async function load () {
  try {
    const [a, b] = await Promise.all([
      catalog.issues(ws.corpus.id, { status: status.value || undefined, profile: profile.value || undefined }),
      catalog.reviewItems(ws.corpus.id)
    ])
    issues.value = a.items
    skipped.value = a.skipped || []
    queue.value = b.items
  } catch (e) { notify.error(e) } finally { loading.value = false }
}
onMounted(load)
watch([status, profile], load)
const lastValidate = computed(() => ws.jobs.find(j => j.kind === 'validate'))
watch(() => ws.jobsVersion, () => {
  const j = runningJob.value && ws.jobs.find(x => x.id === runningJob.value)
  if (j && TERMINAL.has(j.status)) {
    runningJob.value = null
    notify.ok(j.status === 'succeeded' ? `Проверка готова: новых замечаний ${j.result?.issues_created ?? 0}, открытых ${j.result?.issues_open ?? 0}` : 'Проверка завершилась с ошибкой')
    load()
    refreshCorpus()
  } else if (!runningJob.value) load()
})

async function validate () {
  try {
    const r = await jobs.create(ws.corpus.id, { kind: 'validate', target_profiles: ['solar-v1', 'rag-v1'], check_sources: true, run_external_checker: true })
    runningJob.value = r.job_id
    kickJobs()
  } catch (e) { notify.error(e) }
}
function openIssue (i) {
  router.push({ name: 'article', params: { corpusId: ws.corpus.id, documentId: i.document_id }, query: { profile: i.profile, record: i.focus_id || i.record_ids[0] } })
}
function act (it) {
  if (it.kind === 'classification' || it.kind === 'scope') { decide.value = it; return }
  const query = { profile: it.profile }
  if (it.entity_id) query.record = it.entity_id
  router.push({ name: 'article', params: { corpusId: ws.corpus.id, documentId: it.document_id }, query })
}
const ACT = { classification: 'Решить тему', scope: 'Решить', candidate: 'Сравнить версии', source: 'Сверить источник', issue: 'Открыть' }
const KIND_TONE = { classification: 'wait', scope: 'wait', candidate: 'wait', source: 'off', issue: 'warn' }
const counts = computed(() => ({ issues: ws.corpus?.stats?.issues_open ?? issues.value.length, queue: queue.value.length }))
</script>

<template>
  <div class="page checks">
    <div class="page__head">
      <h1 class="page__title">Проверки</h1>
      <Segmented v-model="tab" :options="[{ value: 'issues', label: 'Замечания', count: counts.issues }, { value: 'queue', label: 'Очередь', count: counts.queue }]" label="Раздел проверок" />
      <span class="grow" />
      <span v-if="lastValidate && !ui.mobile" class="checks__last">Последняя проверка {{ fmtDate(lastValidate.finished_at || lastValidate.created_at) }}</span>
      <button v-if="editable && !ui.mobile" class="btn btn--accent" type="button" :disabled="!!runningJob" @click="validate"><ShieldCheck />{{ runningJob ? 'Проверяю…' : 'Запустить проверку' }}</button>
    </div>

    <template v-if="tab === 'issues'">
      <div class="checks__filters">
        <Segmented v-model="status" size="sm" :options="[{ value: 'open', label: 'Открытые' }, { value: 'confirmed', label: 'Подтверждённые' }, { value: 'dismissed', label: 'Отклонённые' }, { value: '', label: 'Все' }]" label="Статус" />
        <span class="grow" />
        <select v-if="!ui.mobile" v-model="profile" class="select select--sm checks__sel" aria-label="Профиль">
          <option value="">Оба профиля</option>
          <option value="solar-v1">Солнечные элементы</option>
          <option value="rag-v1">RAG-системы</option>
        </select>
      </div>
      <ul v-if="skipped.length && !ui.mobile" class="checks__skip">
        <li v-for="s in skipped" :key="s.rule">{{ s.text }}</li>
      </ul>
      <div v-if="loading" class="stack"><div v-for="i in 3" :key="i" class="skeleton" style="height: 120px; border-radius: 12px" /></div>
      <div v-else-if="!issues.length" class="panel empty">
        <h3>{{ status === 'open' ? 'Открытых замечаний нет' : 'Здесь пусто' }}</h3>
        <p>Замечания появляются после проверки: сходимость PCE, Jsc по EQE, шкалы метрик RAG, источники значений.</p>
      </div>
      <div v-else class="checks__list">
        <IssueCard v-for="i in issues" :key="i.id" :issue="i" :editable="editable" show-doc @changed="load(); refreshCorpus()" @open="openIssue" />
      </div>
    </template>

    <template v-else>
      <div v-if="!queue.length && !loading" class="panel empty">
        <h3>Очередь пуста</h3>
        <p>Сюда попадают статьи с неуверенной темой, новые версии после повторного извлечения, сомнительные источники и открытые замечания.</p>
      </div>
      <ul v-else class="panel queue">
        <li v-for="it in queue" :key="it.id" class="queue__row">
          <span class="queue__kind"><Chip :tone="KIND_TONE[it.kind]" :text="REVIEW_KIND[it.kind]" /></span>
          <b class="queue__code">{{ it.publication_code }}</b>
          <span class="queue__sub">
            <span class="queue__text">{{ it.summary }}</span>
            <span class="queue__title">{{ it.title }}<template v-if="it.profile">, {{ profileShort(it.profile) }}</template></span>
          </span>
          <button class="btn btn--sm" :class="{ 'btn--primary': it.kind === 'classification' && editable }" type="button" :disabled="(it.kind === 'classification' || it.kind === 'scope') && !editable" @click="act(it)">{{ ACT[it.kind] }}</button>
        </li>
      </ul>
    </template>
    <ClassificationDialog :open="!!decide" :document-id="decide?.document_id" :code="decide?.publication_code" @close="decide = null" @done="load" />
  </div>
</template>

<style>
.checks { max-width: 1080px; }
.checks__last { color: var(--u-soft); }
.checks__filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.checks__sel { width: auto; min-width: 180px; }
.checks__skip { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; padding: 10px 14px; border-radius: 12px; background: var(--u-fill); box-shadow: inset 0 0 0 1px var(--u-line); color: var(--u-muted); }
.checks__skip li { display: flex; gap: 10px; }
.checks__skip li::before { content: ""; width: 6px; height: 6px; margin-top: 7px; border-radius: 50%; background: var(--u-soft); flex: none; }
.checks__list { display: flex; flex-direction: column; gap: 8px; }
.queue { overflow: hidden; }
.queue__row { display: grid; grid-template-columns: 150px 56px minmax(0, 1fr) auto; align-items: center; gap: 0 12px; min-height: 56px; padding: 8px 12px 8px 16px; }
.queue__row + .queue__row { box-shadow: inset 0 1px 0 var(--u-line); }
.queue__code { font-weight: 500; }
.queue__sub { display: flex; flex-direction: column; min-width: 0; }
.queue__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue__title { font-size: 12px; line-height: 16px; color: var(--u-soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 719px) {
  .page__head .seg { order: 5; flex-basis: 100%; }
  .queue__row { grid-template-columns: auto minmax(0, 1fr); grid-template-rows: auto auto auto; gap: 6px 10px; padding: 12px 14px; }
  .queue__kind { grid-column: 1; grid-row: 1; }
  .queue__code { grid-column: 2; grid-row: 1; justify-self: end; }
  .queue__sub { grid-column: 1 / 3; grid-row: 2; }
  .queue__text, .queue__title { white-space: normal; }
  .queue__row .btn { grid-column: 1 / 3; grid-row: 3; }
}
</style>
