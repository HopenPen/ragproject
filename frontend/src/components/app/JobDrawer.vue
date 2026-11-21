<!-- Назначение файла: подробности задания: этап каждой статьи, ошибки, отмена между этапами и повтор упавших. -->
<script setup>
import { computed, ref, watch } from 'vue'
import { RotateCcw, CircleStop } from '@lucide/vue'
import Drawer from '../ui/Drawer.vue'
import Chip from '../ui/Chip.vue'
import Progress from '../ui/Progress.vue'
import { jobs } from '../../api/index.js'
import { ws, kickJobs } from '../../stores/workspace.js'
import { canEdit } from '../../stores/session.js'
import { notify } from '../../stores/toasts.js'
import { JOB_STATUS, JOB_KIND, STAGE, TERMINAL } from '../../lib/labels.js'
import { fmtDate } from '../../lib/format.js'

const props = defineProps({ open: Boolean, jobId: String })
const emit = defineEmits(['close'])
const job = ref(null)
const items = ref([])
const busy = ref(false)

async function load () {
  if (!props.jobId) return
  try {
    const [j, list] = await Promise.all([jobs.get(props.jobId), jobs.items(props.jobId)])
    job.value = j
    items.value = list
  } catch (e) { notify.error(e) }
}
watch(() => [props.open, props.jobId], ([o]) => { if (o) load() }, { immediate: true })
watch(() => ws.jobsVersion, () => { if (props.open) load() })

const active = computed(() => job.value && !TERMINAL.has(job.value.status))
const retryable = computed(() => items.value.some(i => ['failed', 'cancelled', 'blocked_external_configuration'].includes(i.status)) || ['failed', 'cancelled'].includes(job.value?.status))
const editable = computed(() => canEdit(ws.corpus))
async function cancel () {
  busy.value = true
  try { await jobs.cancel(job.value.id); notify.info('Отмена запрошена: текущий этап закончится, остальные статьи не начнутся'); kickJobs(); load() } catch (e) { notify.error(e) } finally { busy.value = false }
}
async function retry () {
  busy.value = true
  try { await jobs.retry(job.value.id); notify.ok('Повтор запущен для статей с ошибками'); kickJobs(); emit('close') } catch (e) { notify.error(e) } finally { busy.value = false }
}
function itemProgress (i) {
  return i.status === 'running' && i.progress?.total ? i.progress.done / i.progress.total : null
}
</script>

<template>
  <Drawer :open="open" :title="job ? `${JOB_KIND[job.kind]}, ${fmtDate(job.created_at)}` : 'Задание'" width="600px" @close="emit('close')">
    <template #subtitle>
      <p v-if="job" class="muted jd__sub">
        <Chip :tone="JOB_STATUS[job.status]?.tone" :text="JOB_STATUS[job.status]?.text || job.status" />
        <span v-if="job.created_by">запустил {{ job.created_by }}</span>
      </p>
    </template>
    <div v-if="job" class="stack jd">
      <p v-if="job.error" class="jd__error">{{ job.error.message }}</p>
      <table v-if="items.length" class="table jd__table">
        <thead><tr><th>Код</th><th>Этап</th><th>Статус</th></tr></thead>
        <tbody>
          <tr v-for="i in items" :key="i.id">
            <td class="nowrap"><b>{{ i.publication_code }}</b></td>
            <td>
              <span>{{ STAGE[i.stage] || i.stage }}</span>
              <Progress v-if="i.status === 'running'" :value="itemProgress(i)" class="jd__bar" />
              <p v-if="i.error" class="jd__item-error">{{ i.error.message }}</p>
            </td>
            <td><Chip :tone="JOB_STATUS[i.status]?.tone" :text="JOB_STATUS[i.status]?.text || i.status" /></td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="job.stage" class="muted">Этап: {{ STAGE[job.stage] || job.stage }}</p>
    </div>
    <div v-else class="skeleton" style="height: 240px" />
    <template v-if="job && editable && (active || retryable)" #footer>
      <button v-if="active" class="btn" type="button" :disabled="busy || job.status === 'cancel_requested'" @click="cancel"><CircleStop />Отменить</button>
      <button v-if="!active && retryable" class="btn btn--primary" type="button" :disabled="busy" @click="retry"><RotateCcw />Повторить упавшие</button>
    </template>
  </Drawer>
</template>

<style>
.jd__sub { display: flex; align-items: center; gap: 10px; margin-top: 6px; font-size: var(--fs-sm); }
.jd__error { padding: 10px 12px; border-radius: var(--r-md); background: var(--danger-fill); color: var(--danger); }
.jd__table td { vertical-align: top; padding-top: 11px; padding-bottom: 11px; }
.jd__bar { margin-top: 6px; max-width: 220px; }
.jd__item-error { margin-top: 4px; font-size: var(--fs-sm); color: var(--danger); }
</style>
