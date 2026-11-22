<!-- Назначение файла: форма записи графа по схеме профиля (GET /domain-profiles/{id}): типы полей, словари,
     ссылки на другие записи. Сохраняет только изменённые поля с обязательной причиной и If-Match версии графа. -->
<script setup>
import { computed, ref, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import { publications } from '../../api/index.js'
import { ws } from '../../stores/workspace.js'
import { notify } from '../../stores/toasts.js'
import { ENTITY, ID_FIELD, fieldLabel, valueLabel } from '../../lib/labels.js'
import { MAIN_FIELDS, natural } from '../../lib/records.js'
import { fmtUnit } from '../../lib/format.js'

const props = defineProps({ open: Boolean, mode: String, type: String, item: Object, profile: String, publicationId: String, graph: Object, etag: String })
const emit = defineEmits(['close', 'saved', 'stale'])
const values = ref({})
const reason = ref('')
const errors = ref({})
const common = ref('')
const busy = ref(false)

const schema = computed(() => ws.profiles[props.profile]?.entities.find(e => e.type === props.type))
const idField = computed(() => ID_FIELD[props.type])
const fields = computed(() => schema.value?.fields || [])
const main = computed(() => {
  const names = [idField.value, ...(MAIN_FIELDS[props.type] || [])]
  return fields.value.filter(f => names.includes(f.name) && !(f.name === idField.value && props.mode === 'edit'))
})
const rest = computed(() => fields.value.filter(f => !main.value.includes(f) && f.name !== idField.value))

function nextId () {
  const list = props.graph?.entities?.[props.type] || []
  const prefix = { solar_result: 'R', rag_result: 'R', device: 'D', measurement: 'M', material: 'M', layer: 'L', configuration: 'C', dataset: 'DS', task: 'T', experiment: 'E' }[props.type] || 'X'
  let n = list.length + 1
  while (list.some(x => x[idField.value] === `${prefix}${n}`)) n++
  return `${prefix}${n}`
}
function toInput (f, v) {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.join('; ')
  if (f.type === 'boolean') return v ? 'true' : 'false'
  return String(v)
}
watch(() => props.open, o => {
  if (!o) return
  errors.value = {}
  common.value = ''
  reason.value = ''
  const v = {}
  for (const f of fields.value) v[f.name] = toInput(f, props.item?.[f.name])
  if (props.mode === 'create') v[idField.value] = nextId()
  values.value = v
}, { immediate: true })

function refOptions (f) {
  const target = ws.profiles[props.profile]?.entities.find(e => e.type === f.ref)
  return (props.graph?.entities?.[f.ref] || []).map(x => x[target.id_field]).sort(natural)
}
const changed = computed(() => {
  const out = {}
  for (const f of fields.value) {
    const before = props.mode === 'create' ? '' : toInput(f, props.item?.[f.name])
    if (values.value[f.name] !== before) out[f.name] = values.value[f.name] === '' ? null : values.value[f.name]
  }
  return out
})
const dirty = computed(() => Object.keys(changed.value).length > 0)

async function save () {
  errors.value = {}
  common.value = ''
  if (!dirty.value) { common.value = 'Нет изменений.'; return }
  busy.value = true
  try {
    const body = { profile: props.profile, reason: reason.value.trim(), values: changed.value }
    const res = props.mode === 'create'
      ? await publications.createEntity(props.publicationId, props.type, body, props.etag)
      : await publications.updateEntity(props.publicationId, props.type, props.item[idField.value], body, props.etag)
    notify.ok(props.mode === 'create' ? `Запись ${changed.value[idField.value] || ''} добавлена, версия ${res.data.revision_number}` : `Сохранено, версия ${res.data.revision_number}`)
    emit('saved', res)
    emit('close')
  } catch (e) {
    if (e.status === 412) { common.value = e.message; emit('stale') } else if (e.details?.field) errors.value[e.details.field] = e.message
    else common.value = e.message
  } finally {
    busy.value = false
  }
}
const title = computed(() => props.mode === 'create' ? `Новая запись: ${ENTITY[props.type]?.one}` : `${ENTITY[props.type]?.one?.replace(/^./, c => c.toUpperCase())} ${props.item?.[idField.value] || ''}`)
</script>

<template>
  <Modal :open="open" :title="title" width="620px" @close="emit('close')">
    <form id="entity-form" class="eform" @submit.prevent="save">
      <div class="eform__grid">
        <label v-for="f in main" :key="f.name" class="field" :class="{ 'eform__wide': f.type === 'text' }">
          <span class="field__label">{{ fieldLabel(f.name) }}<span v-if="f.required" class="field__req" aria-hidden="true">*</span><span v-if="f.unit" class="muted">, {{ fmtUnit(f.unit) }}</span></span>
          <select v-if="f.type === 'enum' || f.type === 'boolean' || (f.type === 'ref' && !f.multiple)" v-model="values[f.name]" class="select" :aria-invalid="!!errors[f.name]">
            <option value="">не указано</option>
            <template v-if="f.type === 'enum'"><option v-for="o in f.vocab" :key="o" :value="o">{{ valueLabel(f.name, o) }}</option></template>
            <template v-else-if="f.type === 'boolean'"><option value="true">да</option><option value="false">нет</option></template>
            <template v-else><option v-for="o in refOptions(f)" :key="o" :value="o">{{ o }}</option></template>
          </select>
          <textarea v-else-if="f.type === 'text'" v-model="values[f.name]" class="textarea" rows="2" :aria-invalid="!!errors[f.name]" />
          <input v-else v-model="values[f.name]" class="input" :inputmode="['number', 'integer'].includes(f.type) ? 'decimal' : 'text'" :aria-invalid="!!errors[f.name]" :placeholder="f.multiple ? 'через ;' : ''">
          <span v-if="errors[f.name]" class="field__error">{{ errors[f.name] }}</span>
        </label>
      </div>
      <details v-if="rest.length" class="eform__more">
        <summary>Остальные поля ({{ rest.length }})</summary>
        <div class="eform__grid">
          <label v-for="f in rest" :key="f.name" class="field" :class="{ 'eform__wide': f.type === 'text' }">
            <span class="field__label">{{ fieldLabel(f.name) }}<span v-if="f.unit" class="muted">, {{ fmtUnit(f.unit) }}</span></span>
            <select v-if="f.type === 'enum' || f.type === 'boolean' || (f.type === 'ref' && !f.multiple)" v-model="values[f.name]" class="select">
              <option value="">не указано</option>
              <template v-if="f.type === 'enum'"><option v-for="o in f.vocab" :key="o" :value="o">{{ valueLabel(f.name, o) }}</option></template>
              <template v-else-if="f.type === 'boolean'"><option value="true">да</option><option value="false">нет</option></template>
              <template v-else><option v-for="o in refOptions(f)" :key="o" :value="o">{{ o }}</option></template>
            </select>
            <textarea v-else-if="f.type === 'text'" v-model="values[f.name]" class="textarea" rows="2" />
            <input v-else v-model="values[f.name]" class="input" :inputmode="['number', 'integer'].includes(f.type) ? 'decimal' : 'text'">
            <span v-if="errors[f.name]" class="field__error">{{ errors[f.name] }}</span>
          </label>
        </div>
      </details>
      <label class="field eform__reason">
        <span class="field__label">Причина правки</span>
        <textarea v-model="reason" class="textarea" rows="2" :aria-invalid="!!errors.reason" placeholder='Например: "В таблице 1 указано 78.0, модель прочитала 75.0"' />
        <span v-if="errors.reason" class="field__error">{{ errors.reason }}</span>
        <span v-else class="field__hint">Сохранение создаст новую версию графа. Прежняя останется в истории.</span>
      </label>
      <p v-if="common" class="field__error" role="alert">{{ common }}</p>
    </form>
    <template #footer>
      <button class="btn btn--ghost" type="button" @click="emit('close')">Отмена</button>
      <button class="btn btn--primary" type="submit" form="entity-form" :disabled="busy || !dirty">{{ mode === 'create' ? 'Добавить запись' : 'Сохранить правку' }}</button>
    </template>
  </Modal>
</template>

<style>
.eform__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px 18px; }
.eform__wide { grid-column: 1 / -1; }
.eform__more { margin-top: 18px; }
.eform__more summary { width: max-content; color: var(--pencil); font-weight: 500; margin-bottom: 14px; cursor: pointer; }
.eform__more summary:hover { color: var(--ink); }
.eform__reason { margin-top: 20px; padding-top: 18px; box-shadow: inset 0 1px 0 var(--rule); }
@media (max-width: 719px) { .eform__grid { grid-template-columns: 1fr; } }
</style>
