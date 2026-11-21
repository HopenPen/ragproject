<!-- Назначение файла: полоса текущей обработки над списком документов: сколько готово, что идёт сейчас,
     ожидание решения по теме. Опрос заданий ведёт stores/workspace.js. -->
<script setup>
import { computed, ref } from 'vue'
import { X, Pause, Play } from '@lucide/vue'
import Progress from '../ui/Progress.vue'
import JobDrawer from './JobDrawer.vue'
import ClassificationDialog from './ClassificationDialog.vue'
import { ws } from '../../stores/workspace.js'
import { canEdit } from '../../stores/session.js'
import { ui } from '../../stores/ui.js'
import { JOB_KIND, STAGE, TERMINAL } from '../../lib/labels.js'
import { countText } from '../../lib/format.js'
import { jobs } from '../../api/index.js'
import { kickJobs } from '../../stores/workspace.js'
import { notify } from '../../stores/toasts.js'

const props = defineProps({ waitingDocs: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const dismissed = ref(new Set())
const drawer = ref(null)
const decide = ref(null)
const busy = ref(false)
async function changePause () {
  busy.value = true
  try {
    await (job.value.status === 'paused' ? jobs.resume(job.value.id) : jobs.pause(job.value.id))
    kickJobs()
  } catch (e) { notify.error(e) } finally { busy.value = false }
}

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
  if (c.value.blocked) parts.push(`нужен повтор ${c.value.blocked}`)
  if (c.value.failed) parts.push(`ошибок ${c.value.failed}`)
  if (c.value.cancelled) parts.push(`отменено ${c.value.cancelled}`)
  return parts.join(', ')
})
</script>

<template>
  <div v-if="job" class="jbanner" :class="{ 'jbanner--wait': waiting }">
    <span class="jbanner__mark" :class="job.status === 'paused' ? 'is-paused' : waiting ? 'is-wait' : finished ? 'is-done' : 'is-run'" aria-hidden="true" />
    <p class="jbanner__title">
      <template v-if="job.status === 'paused'">Обработка приостановлена</template>
      <template v-else-if="job.status === 'pause_requested'">Приостанавливается после текущего этапа…</template>
      <template v-else-if="waiting">{{ JOB_KIND[job.kind] }} ждёт решения по теме{{ waitingDoc ? ` ${waitingDoc.publication_code}` : '' }}</template>
      <template v-else-if="finished">{{ JOB_KIND[job.kind] }} завершена</template>
      <template v-else>{{ JOB_KIND[job.kind] }}: {{ doneCount }} из {{ countText(c.total || 0, ['статьи', 'статей', 'статей']) }}</template>
      <span v-if="!waiting && !ui.mobile" class="jbanner__sub"><template v-if="!finished && job.stage_document">{{ job.stage_document }}, {{ (STAGE[job.stage] || job.stage).toLowerCase() }}</template><template v-else-if="finished">{{ summary }}</template></span>
    </p>
    <span class="grow" />
    <button v-if="canEdit(ws.corpus) && ['queued', 'running', 'waiting_review', 'paused'].includes(job.status)" class="btn btn--sm" type="button" :disabled="busy" @click="changePause"><Play v-if="job.status === 'paused'" /><Pause v-else />{{ job.status === 'paused' ? 'Продолжить' : 'Приостановить' }}</button>
    <button v-if="waiting && waitingDoc && canEdit(ws.corpus)" class="btn btn--primary btn--sm" type="button" @click="decide = waitingDoc">Решить тему</button>
    <button class="btn btn--ghost btn--sm" type="button" @click="drawer = job.id">Подробнее</button>
    <button v-if="finished" class="btn btn--ghost btn--icon btn--sm" type="button" aria-label="Скрыть" @click="dismissed.add(job.id)"><X /></button>
    <Progress v-if="!finished && !waiting && job.status !== 'paused'" :value="value" class="jbanner__bar" />
    <JobDrawer :open="!!drawer" :job-id="drawer" @close="drawer = null" />
    <ClassificationDialog :open="!!decide" :document-id="decide?.id" :code="decide?.publication_code" @close="decide = null" @done="emit('changed')" />
  </div>
</template>

<style>
/* полоса задания в одну строку: что идёт и одно действие; прогресс тонкой линией по нижнему краю */
.jbanner { position: relative; display: flex; align-items: center; gap: 10px; min-height: 44px; margin-bottom: 12px; padding: 6px 8px 6px 14px; background: var(--u-bg); border: 1px solid var(--u-border); border-radius: 12px; overflow: hidden; }
.jbanner__mark { width: 14px; height: 14px; flex: none; border-radius: 50%; }
.jbanner__mark.is-run { border: 2px solid color-mix(in oklab, var(--u-accent) 30%, transparent); border-top-color: var(--u-accent); animation: ui-spin 800ms linear infinite; }
.jbanner__mark.is-wait { width: 8px; height: 8px; margin: 0 3px; background: var(--u-ink); }
.jbanner__mark.is-done { width: 8px; height: 8px; margin: 0 3px; background: var(--u-accent); }
.jbanner__mark.is-paused { width: 10px; height: 12px; margin: 0 2px; border-radius: 0; border-left: 3px solid var(--u-muted); border-right: 3px solid var(--u-muted); }
.jbanner__title { min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jbanner__sub { margin-left: 10px; font-weight: 400; color: var(--u-muted); }
.jbanner__bar { position: absolute; left: 0; right: 0; bottom: 0; height: 2px; border-radius: 0; background: transparent; }
@media (max-width: 719px) {
  .jbanner { flex-wrap: wrap; padding: 10px 12px; }
  .jbanner__title { flex: 1 1 calc(100% - 30px); white-space: normal; }
  .jbanner .grow { display: none; }
  .jbanner .btn { flex: 1; }
}
</style>
