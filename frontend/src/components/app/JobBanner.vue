<!-- Назначение файла: полоса текущей обработки над списком документов: сколько готово, что идёт сейчас,
     ожидание решения по теме. Опрос заданий ведёт stores/workspace.js. -->
<script setup>
import { computed, ref } from 'vue'
import { X } from '@lucide/vue'
import Progress from '../ui/Progress.vue'
import Chip from '../ui/Chip.vue'
import JobDrawer from './JobDrawer.vue'
import ClassificationDialog from './ClassificationDialog.vue'
import { ws } from '../../stores/workspace.js'
import { canEdit } from '../../stores/session.js'
import { JOB_KIND, JOB_STATUS, STAGE, TERMINAL } from '../../lib/labels.js'
import { countText } from '../../lib/format.js'

const props = defineProps({ waitingDocs: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const dismissed = ref(new Set())
const drawer = ref(null)
const decide = ref(null)

const job = computed(() => {
  const list = ws.jobs.filter(j => ['process', 'classify'].includes(j.kind) && !dismissed.value.has(j.id))
  const live = list.find(j => !TERMINAL.has(j.status))
  if (live) return live
  const recent = list.find(j => j.finished_at && Date.now() - new Date(j.finished_at).getTime() < 5 * 60000)
  return recent || null
})
const c = computed(() => job.value?.counters || {})
const doneCount = computed(() => (c.value.succeeded || 0) + (c.value.failed || 0) + (c.value.blocked || 0) + (c.value.cancelled || 0) + (c.value.waiting_review || 0))
const value = computed(() => c.value.total ? doneCount.value / c.value.total : null)
const waiting = computed(() => job.value?.status === 'waiting_review')
const waitingDoc = computed(() => props.waitingDocs[0] || null)
const finished = computed(() => job.value && TERMINAL.has(job.value.status))
const summary = computed(() => {
  const parts = []
  if (c.value.succeeded) parts.push(`готово ${c.value.succeeded}`)
  if (c.value.waiting_review) parts.push(`ждёт решения ${c.value.waiting_review}`)
  if (c.value.blocked) parts.push(`без модели ${c.value.blocked}`)
  if (c.value.failed) parts.push(`ошибок ${c.value.failed}`)
  if (c.value.cancelled) parts.push(`отменено ${c.value.cancelled}`)
  const text = parts.join(', ')
  return text ? text[0].toUpperCase() + text.slice(1) + '.' : ''
})
</script>

<template>
  <div v-if="job" class="jbanner" :class="{ 'jbanner--wait': waiting }">
    <div class="jbanner__text">
      <p class="jbanner__title">
        <template v-if="waiting">{{ JOB_KIND[job.kind] }} ждёт решения по теме<template v-if="waitingDoc">: {{ waitingDoc.publication_code }}</template></template>
        <template v-else-if="finished">{{ JOB_KIND[job.kind] }} завершена</template>
        <template v-else>{{ JOB_KIND[job.kind] }}: {{ doneCount }} из {{ countText(c.total || 0, ['статьи', 'статей', 'статей']) }}</template>
        <Chip v-if="finished" :tone="JOB_STATUS[job.status]?.tone" :text="JOB_STATUS[job.status]?.text" />
      </p>
      <p class="jbanner__sub muted">
        <template v-if="!finished && job.stage_document">{{ job.stage_document }}: {{ (STAGE[job.stage] || job.stage).toLowerCase() }}. </template>
        <span v-if="waiting" class="jbanner__why">Остальные статьи обработаны, задание продолжится после решения. </span>
        {{ summary }}
      </p>
      <Progress v-if="!finished && !waiting" :value="value" class="jbanner__bar" />
    </div>
    <div class="jbanner__actions">
      <button v-if="waiting && waitingDoc && canEdit(ws.corpus)" class="btn btn--primary btn--sm" type="button" @click="decide = waitingDoc">Решить</button>
      <button class="btn btn--sm" type="button" @click="drawer = job.id">Подробнее</button>
      <button v-if="finished" class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Скрыть" @click="dismissed.add(job.id)"><X /></button>
    </div>
    <JobDrawer :open="!!drawer" :job-id="drawer" @close="drawer = null" />
    <ClassificationDialog :open="!!decide" :document-id="decide?.id" :code="decide?.publication_code" @close="decide = null" @done="emit('changed')" />
  </div>
</template>

<style>
.jbanner { display: flex; align-items: center; gap: var(--s-4); margin-bottom: var(--s-4); padding: 12px 14px 12px 16px; border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: var(--r-lg); background: var(--surface); }
.jbanner--wait { border-left-color: var(--warn-line); }
.jbanner__text { flex: 1; min-width: 0; }
.jbanner__title { display: flex; align-items: center; gap: 10px; font-weight: 500; flex-wrap: wrap; }
.jbanner__sub { margin-top: 2px; font-size: var(--fs-sm); }
.jbanner__bar { margin-top: 10px; max-width: 520px; }
.jbanner__actions { display: flex; gap: 6px; flex: none; }
@media (max-width: 719px) {
  .jbanner__why { display: none; }
  .jbanner { flex-direction: column; align-items: stretch; gap: 10px; }
  .jbanner__actions .btn { flex: 1; }
}
</style>
