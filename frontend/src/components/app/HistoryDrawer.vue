<!-- Назначение файла: история публикации: версии графа профиля (активная, кандидаты, прежние) с разницей
     от активной и активацией кандидата, и журнал действий с автором и причиной. -->
<script setup>
import { computed, ref, watch } from 'vue'
import Drawer from '../ui/Drawer.vue'
import Chip from '../ui/Chip.vue'
import Segmented from '../ui/Segmented.vue'
import { publications } from '../../api/index.js'
import { askReason } from '../../stores/dialogs.js'
import { notify } from '../../stores/toasts.js'
import { fmtDate } from '../../lib/format.js'
import { profileTitle } from '../../lib/labels.js'

const props = defineProps({ open: Boolean, publicationId: String, profile: String, etag: String, editable: Boolean, activeRevisionId: String })
const emit = defineEmits(['close', 'activated'])
const tab = ref('versions')
const versions = ref([])
const audit = ref([])
const busy = ref(false)

async function load () {
  try {
    const [v, a] = await Promise.all([publications.versions(props.publicationId, props.profile), publications.audit(props.publicationId)])
    versions.value = v
    audit.value = a
  } catch (e) { notify.error(e) }
}
watch(() => props.open, o => { if (o) load() }, { immediate: true })

const STATUS = { active: { text: 'Активная', tone: 'ok' }, candidate: { text: 'Кандидат', tone: 'wait' }, superseded: { text: 'Прежняя', tone: 'off' } }
const ORIGIN = { machine: 'модель', manual: 'вручную', reprocess: 'повторное извлечение' }
const ACTION = {
  'graph.created': 'создан граф', 'graph.updated': 'правка записи', 'graph.candidate': 'новый кандидат', 'graph.excluded': 'исключено из профиля',
  'entity.created': 'добавлена запись', 'entity.deleted': 'удалена запись', 'evidence.confirmed': 'источник подтверждён', 'evidence.rejected': 'источник отклонён',
  'evidence.added': 'добавлен источник', 'issue.confirmed': 'замечание подтверждено', 'issue.dismissed': 'замечание отклонено', 'issue.open': 'замечание открыто снова',
  'version.activated': 'активирована версия', 'classification.reviewed': 'решение по теме'
}
const active = computed(() => versions.value.find(v => v.status === 'active'))
function diffText (d) {
  if (!d) return ''
  const parts = []
  if (d.added) parts.push(`+${d.added} новых`)
  if (d.changed) parts.push(`${d.changed} изменено`)
  if (d.removed) parts.push(`${d.removed} удалено`)
  return parts.length ? `От активной: ${parts.join(', ')}` : 'Совпадает с активной'
}
async function activate (v) {
  const stale = v.based_on_revision_id && active.value && v.based_on_revision_id !== active.value.revision_id
  const reason = await askReason({
    title: `Сделать активной версию ${v.number}?`,
    text: stale ? `Кандидат собран до версии ${active.value.number}. Правки, сделанные после, в нём не будет: проверьте разницу.` : 'Активная версия попадёт в результаты, сравнения и выгрузку. Текущая останется в истории.',
    confirm: 'Сделать активной',
    placeholder: 'Например: повторное извлечение нашло Jsc и FF прибора D1'
  })
  if (!reason) return
  busy.value = true
  try {
    const res = await publications.activate(props.publicationId, v.revision_id, props.profile, props.etag, reason)
    notify.ok(`Активна версия ${v.number}`)
    emit('activated', res)
    load()
  } catch (e) { notify.error(e) } finally { busy.value = false }
}
</script>

<template>
  <Drawer :open="open" title="История статьи" width="560px" @close="emit('close')">
    <template #subtitle><p class="muted hist__sub">{{ profileTitle(profile) }}</p></template>
    <Segmented v-model="tab" :options="[{ value: 'versions', label: 'Версии', count: versions.length }, { value: 'audit', label: 'Журнал', count: audit.length }]" label="Раздел истории" />
    <ol v-if="tab === 'versions'" class="hist">
      <li v-for="v in versions" :key="v.revision_id" class="hist__item" :class="{ 'is-active': v.status === 'active' }">
        <div class="hist__top">
          <b class="num">Версия {{ v.number }}</b>
          <Chip :tone="STATUS[v.status]?.tone" :text="STATUS[v.status]?.text || v.status" />
          <span class="grow" />
          <span class="faint">{{ fmtDate(v.created_at) }}</span>
        </div>
        <p class="hist__who">{{ ORIGIN[v.origin] || v.origin }}<template v-if="v.origin === 'manual'">: {{ v.author_name }}</template><template v-if="v.model_id">, {{ v.model_id }}</template></p>
        <p v-if="v.reason" class="hist__reason">{{ v.reason }}</p>
        <p v-if="v.diff_from_active" class="hist__diff muted">{{ diffText(v.diff_from_active) }}</p>
        <button v-if="v.status === 'candidate' && editable" class="btn btn--sm btn--primary hist__btn" type="button" :disabled="busy" @click="activate(v)">Сделать активной</button>
      </li>
    </ol>
    <ol v-else class="hist">
      <li v-for="a in audit" :key="a.id" class="hist__item">
        <div class="hist__top"><b>{{ ACTION[a.action] || a.action }}</b><span class="grow" /><span class="faint">{{ fmtDate(a.at) }}</span></div>
        <p class="hist__who">{{ a.actor }}<template v-if="a.target">, {{ a.target }}</template></p>
        <p v-if="a.reason" class="hist__reason">{{ a.reason }}</p>
      </li>
      <li v-if="!audit.length" class="muted">Записей нет.</li>
    </ol>
  </Drawer>
</template>

<style>
.hist__sub { margin-top: 2px; font-size: var(--fs-sm); }
.hist { margin-top: var(--s-4); display: flex; flex-direction: column; }
.hist__item { position: relative; padding: 12px 0 14px 18px; border-left: 2px solid var(--line); }
.hist__item::before { content: ""; position: absolute; left: -6px; top: 17px; width: 10px; height: 10px; border-radius: 50%; background: var(--surface); border: 2px solid var(--line-strong); }
.hist__item.is-active::before { border-color: var(--accent); background: var(--accent); }
.hist__top { display: flex; align-items: center; gap: 10px; font-size: var(--fs-md); }
.hist__top .faint { font-size: var(--fs-sm); }
.hist__who { margin-top: 3px; font-size: var(--fs-sm); color: var(--ink-2); }
.hist__reason { margin-top: 6px; font-size: var(--fs-sm); color: var(--muted); }
.hist__diff { margin-top: 6px; font-size: var(--fs-sm); }
.hist__btn { margin-top: 10px; }
</style>
