<!-- Назначение файла: проверки корпуса: замечания научных правил с решением редактора и единая очередь
     (тема статьи, рамки профиля, новые версии, сомнительные источники, открытые замечания).
     Запуск проверки создаёт задание validate, замечания пересчитываются по активным версиям. -->
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
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
const KIND_TONE = { classification: 'wait', scope: 'wait', candidate: 'wait', source: 'plain', issue: 'warn' }
const counts = computed(() => ({ issues: ws.corpus?.stats?.issues_open ?? issues.value.length, queue: queue.value.length }))
</script>

<template>
  <div class="page checks">
    <div class="page__head">
      <h1 class="page__title">Проверки</h1>
      <Segmented v-model="tab" :options="[{ value: 'issues', label: 'Замечания', count: counts.issues }, { value: 'queue', label: 'Очередь', count: counts.queue }]" label="Раздел проверок" />
      <span class="grow" />
      <template v-if="tab === 'issues'">
        <select v-model="status" class="select select--sm checks__sel" aria-label="Статус замечаний">
          <option value="open">Открытые</option>
          <option value="confirmed">Подтверждённые</option>
          <option value="dismissed">Отклонённые</option>
          <option value="">Все</option>
        </select>
        <select v-if="!ui.mobile" v-model="profile" class="select select--sm checks__sel" aria-label="Профиль">
          <option value="">Оба профиля</option>
          <option value="solar-v1">Солнечные элементы</option>
          <option value="rag-v1">RAG-системы</option>
        </select>
      </template>
      <button v-if="editable && !ui.mobile" class="btn btn--accent" type="button" :disabled="!!runningJob" :title="lastValidate ? `Последняя проверка ${fmtDate(lastValidate.finished_at || lastValidate.created_at)}` : ''" @click="validate">{{ runningJob ? 'Проверяю…' : 'Запустить проверку' }}</button>
    </div>

    <template v-if="tab === 'issues'">
      <div v-if="loading" class="checks__list"><div v-for="i in 3" :key="i" class="checks__ghost"><span class="skeleton" style="width: 40%; height: 18px" /><span class="skeleton" style="width: 70%; height: 14px" /></div></div>
      <div v-else-if="!issues.length" class="empty">
        <h3>{{ status === 'open' ? 'Открытых замечаний нет' : 'Здесь пусто' }}</h3>
        <p>Замечания появляются после проверки: сходимость PCE, Jsc по EQE, шкалы метрик RAG, источники значений.</p>
      </div>
      <div v-else class="checks__list">
        <IssueCard v-for="i in issues" :key="i.id" :issue="i" :editable="editable" show-doc @changed="load(); refreshCorpus()" @open="openIssue" />
      </div>
      <p v-for="sk in skipped" v-show="!ui.mobile && !loading" :key="sk.rule" class="checks__skip">{{ sk.text }}</p>
    </template>

    <template v-else>
      <div v-if="!queue.length && !loading" class="empty">
        <h3>Очередь пуста</h3>
        <p>Сюда попадают статьи с неуверенной темой, новые версии после повторного извлечения, сомнительные источники и открытые замечания.</p>
      </div>
      <table v-else-if="!ui.mobile" class="table queue">
        <thead><tr><th class="queue__kind">Что</th><th class="queue__code">Код</th><th>Суть</th><th class="queue__act"><span class="visually-hidden">Действие</span></th></tr></thead>
        <tbody>
          <tr v-for="it in queue" :key="it.id">
            <td><Chip :tone="KIND_TONE[it.kind]" :text="REVIEW_KIND[it.kind]" /></td>
            <td><b>{{ it.publication_code }}</b></td>
            <td class="queue__sub">
              <span class="queue__text">{{ it.summary }}</span>
              <span class="queue__title">{{ it.title }}<template v-if="it.profile">, {{ profileShort(it.profile) }}</template></span>
            </td>
            <td class="queue__act"><button class="btn btn--sm" :class="{ 'btn--primary': it.kind === 'classification' && editable }" type="button" :disabled="(it.kind === 'classification' || it.kind === 'scope') && !editable" @click="act(it)">{{ ACT[it.kind] }}</button></td>
          </tr>
        </tbody>
      </table>
      <ul v-else class="mqueue">
        <li v-for="it in queue" :key="it.id" class="mqueue__row">
          <span class="mqueue__top"><b>{{ it.publication_code }}</b><Chip :tone="KIND_TONE[it.kind]" :text="REVIEW_KIND[it.kind]" /></span>
          <span class="mqueue__text">{{ it.summary }}</span>
          <button class="btn btn--sm" :class="{ 'btn--primary': it.kind === 'classification' && editable }" type="button" :disabled="(it.kind === 'classification' || it.kind === 'scope') && !editable" @click="act(it)">{{ ACT[it.kind] }}</button>
        </li>
      </ul>
    </template>
    <ClassificationDialog :open="!!decide" :document-id="decide?.document_id" :code="decide?.publication_code" @close="decide = null" @done="load" />
  </div>
</template>

<style>
.checks { max-width: 1120px; }
.checks__sel { width: auto; min-width: 156px; }
/* замечания: список правок корректора, линейки как в таблице статьи */
.checks__list { box-shadow: inset 0 1.5px 0 var(--rule-strong), inset 0 -1.5px 0 var(--rule-strong); }
.checks__list > * + * { box-shadow: inset 0 1px 0 var(--rule); }
.checks__ghost { display: flex; flex-direction: column; gap: 10px; padding: 22px 0; }
.checks__skip { margin-top: 14px; font-size: 13px; line-height: 18px; color: var(--pencil); max-width: 72ch; }

.queue__kind { width: 168px; }
.queue__code { width: 72px; }
.queue__act { width: 1%; text-align: right; white-space: nowrap; }
.queue td { height: 56px; }
.queue__sub { min-width: 0; }
.queue__text { display: block; max-width: 72ch; }
.queue__title { display: block; max-width: 72ch; font-size: 13px; line-height: 18px; color: var(--pencil); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.mqueue { box-shadow: inset 0 1.5px 0 var(--rule-strong); }
.mqueue__row { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 14px 0 16px; }
.mqueue__row + .mqueue__row { box-shadow: inset 0 1px 0 var(--rule); }
.mqueue__top { display: flex; align-items: baseline; gap: 12px; width: 100%; }
.mqueue__top .chip { margin-left: auto; }
.mqueue__text { color: var(--pencil); }
.mqueue__row .btn { margin-top: 4px; }
@media (max-width: 719px) {
  .checks .page__head .seg { order: 5; flex-basis: 100%; }
  .checks__sel { flex: 1; }
}
</style>
