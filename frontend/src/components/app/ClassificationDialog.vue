<!-- Назначение файла: ручное решение по теме статьи (POST /documents/{id}/classifications/review):
     темы, рамки профиля и необязательная причина. Показывает оценку модели и фрагмент, на который она опиралась. -->
<script setup>
import { ref, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import { documents } from '../../api/index.js'
import { notify } from '../../stores/toasts.js'
import { kickJobs } from '../../stores/workspace.js'
import { fmtNum } from '../../lib/format.js'

const props = defineProps({ open: Boolean, documentId: String, code: String })
const emit = defineEmits(['close', 'done'])
const cur = ref(null)
const labels = ref([])
const scope = ref({ 'solar-v1': true, 'rag-v1': true })
const reason = ref('')
const busy = ref(false)
const error = ref('')

watch(() => [props.open, props.documentId], async ([open]) => {
  if (!open) return
  error.value = ''
  reason.value = ''
  cur.value = null
  try {
    const res = await documents.classifications(props.documentId)
    cur.value = res.current
    labels.value = [...(res.current?.labels || [])]
    scope.value = { 'solar-v1': res.current?.scope?.['solar-v1'] ?? true, 'rag-v1': res.current?.scope?.['rag-v1'] ?? true }
  } catch (e) { error.value = e.message }
}, { immediate: true })

const TOPICS = [
  { label: 'solar', profile: 'solar-v1', title: 'Солнечные элементы', hint: 'однопереходные тонкоплёночные приборы' },
  { label: 'rag', profile: 'rag-v1', title: 'RAG-системы', hint: 'поиск плюс генерация, с оценкой качества' }
]
async function submit () {
  busy.value = true
  error.value = ''
  try {
    const sc = {}
    for (const t of TOPICS) if (labels.value.includes(t.label)) sc[t.profile] = scope.value[t.profile]
    await documents.reviewClassification(props.documentId, { expected_revision: cur.value?.revision_id, labels: labels.value, scope: sc, reason: reason.value.trim(), replace_reviewed: cur.value?.origin === 'manual' })
    notify.ok(labels.value.length ? 'Тема сохранена' : 'Статья отмечена как вне тем')
    kickJobs()
    emit('done')
    emit('close')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="`Тема статьи ${code || ''}`" width="560px" @close="emit('close')">
    <div v-if="cur" class="stack cls">
      <div class="cls__model">
        <p class="cls__h">Оценка модели</p>
        <dl class="cls__scores">
          <div v-for="t in TOPICS" :key="t.label"><dt>{{ t.title }}</dt><dd class="num">{{ fmtNum(cur.scores?.[t.label], 2) }}</dd></div>
        </dl>
        <p v-if="cur.note" class="cls__note">{{ cur.note }}</p>
        <blockquote v-if="cur.evidence?.[0]" class="quote">{{ cur.evidence[0].fragment }}</blockquote>
        <p v-if="cur.evidence?.[0]" class="cls__where">Стр. {{ cur.evidence[0].page }}</p>
      </div>
      <fieldset class="cls__topics">
        <legend class="field__label cls__legend">Ваше решение</legend>
        <div v-for="t in TOPICS" :key="t.label" class="cls__topic">
          <label class="check"><input v-model="labels" type="checkbox" class="cb" :value="t.label"><span>{{ t.title }}<span class="muted">, {{ t.hint }}</span></span></label>
          <div v-if="labels.includes(t.label)" class="cls__scope">
            <label class="check"><input v-model="scope[t.profile]" type="radio" :value="true">в рамках профиля</label>
            <label class="check"><input v-model="scope[t.profile]" type="radio" :value="false">вне рамок (например, тандем)</label>
          </div>
        </div>
        <p v-if="!labels.length" class="field__hint">Без отмеченных тем статья попадёт в выгрузку только библиографией.</p>
      </fieldset>
      <label class="field">
        <span class="field__label">Причина</span>
        <textarea v-model="reason" class="textarea" rows="2" placeholder='Например: "В разделе 2 есть устройство и J-V, тема подтверждена"' />
      </label>
      <p v-if="error" class="field__error" role="alert">{{ error }}</p>
    </div>
    <div v-else-if="error" class="field__error">{{ error }}</div>
    <div v-else class="skeleton" style="height: 220px" />
    <template #footer>
      <button class="btn btn--ghost" type="button" @click="emit('close')">Отмена</button>
      <button class="btn btn--primary" type="button" :disabled="busy || !cur" @click="submit">Сохранить решение</button>
    </template>
  </Modal>
</template>

<style>
.cls { gap: 22px; }
.cls__h { margin-bottom: 8px; color: var(--pencil); }
.cls__legend { margin-bottom: 10px; }
.cls__scores { display: flex; gap: 40px; margin-bottom: 12px; }
.cls__scores div { display: flex; flex-direction: column-reverse; }
.cls__scores dt { font-size: 13px; line-height: 18px; color: var(--pencil); }
.cls__scores dd { font-size: var(--t-26); line-height: 32px; font-weight: 600; letter-spacing: -0.02em; }
.cls__note { margin-bottom: 12px; max-width: 60ch; }
.cls__where { margin-top: 6px; font-size: 13px; line-height: 18px; color: var(--pencil); }
.cls__topics { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.cls__scope { display: flex; gap: 20px; margin: 8px 0 0 24px; flex-wrap: wrap; }
</style>
